"""`.optim-jev/logs/jev_router/<session_id>.jsonl`: each session's routed spawns and turn outcomes."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Sequence
from typing import Any

from ...core import logs, pricing, report
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


def _label(record: dict[str, Any]) -> str:
    effort = record.get("effort")
    return f"{record['model']} · {effort}" if effort else record["model"]


def why(records: Sequence[dict[str, Any]], session_id: str) -> str:
    mine = [r for r in _spawns(records) if r.get("session_id") == session_id][-WHY_SPAWNS:]
    if not mine:
        return "jev-router: no subagent routed yet in this session"
    lines = [f"Last {len(mine)} routed subagent(s), newest last:"]
    for r in mine:
        probs = ", ".join(f"{k} {v:.0%}" for k, v in (r.get("probabilities") or {}).items())
        effort_probs = ", ".join(f"{k} {v:.0%}" for k, v in (r.get("effort_probabilities") or {}).items())
        up = f" · ⬆{r['escalated']}" if r.get("escalated") else ""
        failed = f" · Jev failed: {r['jev_failed']}" if r.get("jev_failed") else ""
        trimmed = " · input trimmed to fit" if r.get("trimmed") else ""
        lines.append(
            f"- {r.get('description') or 'subagent'} → {_label(r)} via {r.get('source')}{up} · allowed: "
            f"{'/'.join(r.get('allowed', [])) or 'none'}" + (f" · Jev: {probs}" if probs else "")
            + (f" · effort: {effort_probs}" if effort_probs else "") + trimmed + failed
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
    by_model = Counter(_label(r) for r in spawns)
    sources = Counter(r.get("source") for r in spawns)
    escalations = sum(len(r.get("escalations", [])) for r in records if r.get("kind") == "outcome")
    denials = sum(r.get("denials", 0) for r in records if r.get("kind") == "outcome")
    activity = [("Routed subagents", str(len(spawns)))]
    activity += [(f"  on {m}", f"{c} ({c / len(spawns):.0%})") for m, c in by_model.most_common()]
    activity += [
        ("Decided by Jev", str(sources.get("jev", 0))),
        ("Decided by rules", str(sources.get("rules", 0))),
        ("Decided by Claude (over budget)", str(sources.get("claude", 0))),
        ("Fallback (Jev offline)", str(sources.get("fallback", 0))),
        ("Jev input trimmed", str(sum(1 for r in spawns if r.get("trimmed")))),
        ("Escalations", str(escalations)),
        ("Denied writes", str(denials)),
    ]
    blocks, notes = _cost(records, list(claude))
    return report.render(report.table("Activity", ("Metric", "Value"), activity, right=(1,)), *blocks, notes=notes)


def _cost(records: Sequence[dict[str, Any]], claude: list[dict[str, Any]]) -> tuple[list[list[str]], list[str]]:
    """Measured subagent cost vs. the same tokens on the main model, plus Jev's routing cost."""
    agents = {r["agent_id"] for r in claude if r.get("kind") == "spawned" and r.get("agent_id")}
    turns = [r for r in claude if r.get("kind") == "turn" and r.get("agent_id") in agents]
    _, jev_in, jev_usd = pricing.jev_cost(list(records))
    main = pricing.main_model(claude)
    usd = pricing.usd
    if not turns:
        return [], [f"No routed subagent turns logged yet. Jev routing so far: {jev_in:,} tokens, {usd(jev_usd)}.", pricing.PRICE_NOTE]
    actual = sum(pricing.cost(t) for t in turns)
    on_main = sum(pricing.cost(t, main) for t in turns)
    net = on_main - actual - jev_usd
    tokens = sum(
        t.get(k, 0) for t in turns
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    main_usd = sum(pricing.cost(t) for t in pricing.main_turns(claude))
    cost = report.table(
        f"Cost: {len(agents)} subagent(s), {tokens:,} tokens, vs the main model doing it",
        ("Item", "Basis", "USD"),
        [
            (f"Same work on {main or 'the main model'}", "est.", usd(on_main)),
            ("Subagents on routed models", "measured", usd(actual)),
            ("Jev routing", "measured", usd(jev_usd)),
        ],
        right=(2,),
        total=(report.net_label(net), "", usd(abs(net))),
    )
    return [cost], [
        f"Main loop this session: {usd(main_usd)} (measured).",
        "Estimate leaves out the main loop's own context growth, so the real saving is usually larger.",
        pricing.PRICE_NOTE,
    ]
