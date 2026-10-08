"""`.optim-jev/logs/jev_router/<session_id>.jsonl`: each session's routed spawns and turn outcomes."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Sequence
from typing import Any

from ...core import logs, pricing
from .catalog import ModelInfo

TOOL = "jev_router"
# Learned ladder notes need this many routed spawns for a model before they say anything.
MIN_SAMPLES = 10
WHY_SPAWNS = 5


def append(project_dir: str | os.PathLike[str], session_id: str, record: dict[str, Any]) -> None:
    logs.append(logs.session_file(project_dir, TOOL, session_id), {"session_id": session_id, **record})


def read(project_dir: str | os.PathLike[str], session_id: str) -> list[dict[str, Any]]:
    return logs.read(logs.session_file(project_dir, TOOL, session_id))


def _spawns(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r.get("kind") == "spawn" and r.get("model")]


def learned(records: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Per model, how often its subagents had to escalate, once there are enough samples."""
    routed = Counter(r["model"] for r in _spawns(records))
    escalated = Counter(
        e.get("from") for r in records if r.get("kind") == "outcome" for e in r.get("escalations", [])
    )
    return {
        model: f"{escalated.get(model, 0)}/{count} escalated here"
        for model, count in routed.items()
        if count >= MIN_SAMPLES
    }


def why(records: Sequence[dict[str, Any]], session_id: str) -> str:
    mine = [r for r in _spawns(records) if r.get("session_id") == session_id][-WHY_SPAWNS:]
    if not mine:
        return "jev-router: no subagent routed yet in this session"
    lines = [f"Last {len(mine)} routed subagent(s), newest last:"]
    for r in mine:
        probs = ", ".join(f"{k} {v:.0%}" for k, v in (r.get("probabilities") or {}).items())
        up = f" · ⬆{r['escalated']}" if r.get("escalated") else ""
        failed = f" · Jev failed: {r['jev_failed']}" if r.get("jev_failed") else ""
        lines.append(
            f"- {r.get('description') or 'subagent'} → {r['model']} via {r.get('source')}{up} · allowed: "
            f"{'/'.join(r.get('allowed', [])) or 'none'}" + (f" · Jev: {probs}" if probs else "") + failed
        )
        for f in r.get("files", []):
            lines.append(f"    {f.get('path')}  ← {f.get('rule') or 'no rule'}" + (f" ({f['why']})" if f.get("why") else ""))
    return "\n".join(lines)


def stats(
    records: Sequence[dict[str, Any]], catalog: Sequence[ModelInfo], claude: Sequence[dict[str, Any]] = ()
) -> str:
    spawns = _spawns(records)
    if not spawns:
        return "jev-router: nothing logged yet in this session"
    by_model = Counter(r["model"] for r in spawns)
    share = ", ".join(f"{m} {c / len(spawns):.0%}" for m, c in by_model.most_common())
    sources = Counter(r.get("source") for r in spawns)
    escalations = sum(len(r.get("escalations", [])) for r in records if r.get("kind") == "outcome")
    denials = sum(r.get("denials", 0) for r in records if r.get("kind") == "outcome")
    return "\n".join(
        [
            f"Routed subagents: {len(spawns)} · {share}",
            f"Decided by: Jev {sources.get('jev', 0)} · rules {sources.get('rules', 0)} · fallback {sources.get('fallback', 0)}",
            f"Escalations: {escalations} · denied writes: {denials}",
            *_cost_lines(records, list(claude)),
        ]
    )


def _cost_lines(records: Sequence[dict[str, Any]], claude: list[dict[str, Any]]) -> list[str]:
    """Measured subagent cost vs. the same tokens on the main model, plus Jev's routing cost."""
    agents = {r["agent_id"] for r in claude if r.get("kind") == "spawned" and r.get("agent_id")}
    turns = [r for r in claude if r.get("kind") == "turn" and r.get("agent_id") in agents]
    _, jev_in, jev_usd = pricing.jev_cost(list(records))
    main = pricing.main_model(claude)
    if not turns:
        return ["", f"Jev routing: {jev_in:,} input tokens · {pricing.usd(jev_usd)}", "No routed subagent turns logged yet."]
    actual = sum(pricing.cost(t) for t in turns)
    on_main = sum(pricing.cost(t, main) for t in turns)
    net = on_main - actual - jev_usd
    tokens = sum(
        t.get(k, 0) for t in turns
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    main_usd = sum(pricing.cost(t) for t in pricing.main_turns(claude))
    return [
        "",
        f"Cost of {len(agents)} routed subagent(s), {tokens:,} tokens ({len(turns)} turn(s)):",
        f"  on their routed models (measured)   {pricing.usd(actual)}",
        f"  same tokens on {main or 'the main model'} (est.)   {pricing.usd(on_main)}",
        f"  Jev routing (measured)              {pricing.usd(jev_usd)}",
        f"  net {'saved' if net >= 0 else 'extra'}                           {pricing.usd(abs(net))}",
        f"Main loop this session (measured): {pricing.usd(main_usd)}",
        "Estimate prices the subagents' own tokens at the main model; it leaves out the main loop's context "
        "growth had it done the work itself.",
        pricing.PRICE_NOTE,
    ]
