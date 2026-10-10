"""Claude Code bridge for the skill picker: one JSON request on stdin, one JSON answer on stdout.

    python -m optim_jev.tools.jev_skills.tool <mode>

index      {}                                  -> {count, dirs, names}
shortlist  {session_id, prompt, recent_inputs} -> {picks, context, failed}
loaded     {session_id, skill, shortlisted}    -> {}
why        {session_id}                        -> {text}
stats      {}                                  -> {text}

Every request also carries project_dir and options (this tool reads the `jev_skills_` keys).
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from typing import Any

from ...core import logs, pricing, report
from ..jev_compacter.jev import JevClient
from . import index
from .config import SkillsConfig
from .pick import shortlist

OPTION_PREFIX = "jev_skills_"
LOG_TOOL = "jev_skills"


def _config(request: dict[str, Any]) -> SkillsConfig:
    raw = request.get("options")
    raw = raw if isinstance(raw, dict) else {}
    values = {k[len(OPTION_PREFIX):]: v for k, v in raw.items() if k.startswith(OPTION_PREFIX)}
    if request.get("scope"):
        values["scope"] = request["scope"]
    return SkillsConfig.from_mapping(values)


def _append(project: str, session_id: str, record: dict[str, Any]) -> None:
    logs.append(logs.session_file(project, LOG_TOOL, session_id), {"session_id": session_id, **record})


def index_mode(request: dict[str, Any]) -> dict[str, Any]:
    config = _config(request)
    roster = index.load(request["project_dir"], config.is_global)
    return {
        "count": len(roster),
        # Folders outside the project whose files Claude may read without asking (global scope).
        "dirs": sorted({s.dir for s in roster if s.source != "project"}),
        "names": [s.name for s in roster],
    }


def _note(picks: list[dict[str, Any]], names: list[str] | None) -> str:
    if picks:
        lines = ["optim-jev skill picker (Jev) shortlisted these skills for this request:"]
        for p in picks:
            lines.append(f"- {p['name']} ({p['percent']}%): {p['description']}")
        lines.append("If one fits, load it with the Skill tool; otherwise carry on without a skill.")
        return "\n".join(lines)
    if names is not None:
        return "optim-jev skill picker is offline this turn. Available skills: " + ", ".join(names)
    return ""


def shortlist_mode(request: dict[str, Any]) -> dict[str, Any]:
    config = _config(request)
    project = request["project_dir"]
    roster = index.load(project, config.is_global)
    asker = JevClient(model=config.model, base_url=config.base_url, timeout=20.0)
    recent = [str(t) for t in request.get("recent_inputs") or () if isinstance(t, str)]
    result = shortlist(str(request.get("prompt") or ""), recent, roster, asker, config)
    picks = [
        {"name": s.name, "description": s.description, "source": s.source, "percent": round(100 * p)}
        for s, p in result.picks
    ]
    _append(
        project,
        str(request.get("session_id") or ""),
        {
            "kind": "shortlist",
            "scope": config.scope,
            "prompt": str(request.get("prompt") or "")[:160],
            "roster": len(roster),
            "asked": result.asked,
            "calls": result.calls,
            "picks": [{"name": p["name"], "percent": p["percent"]} for p in picks],
            "failed": result.failed,
            "trimmed": result.trimmed,
            "jev": asker.usage(),
        },
    )
    return {
        "picks": [p["name"] for p in picks],
        "context": _note(picks, [s.name for s in roster] if result.failed and roster else None),
        "failed": result.failed,
    }


def loaded_mode(request: dict[str, Any]) -> dict[str, Any]:
    _append(
        request["project_dir"],
        str(request.get("session_id") or ""),
        {
            "kind": "loaded",
            "skill": request.get("skill"),
            "shortlisted": bool(request.get("shortlisted")),
        },
    )
    return {}


def why_mode(request: dict[str, Any]) -> dict[str, Any]:
    path = logs.session_file(request["project_dir"], LOG_TOOL, str(request.get("session_id") or ""))
    mine = [r for r in logs.read(path) if r.get("kind") == "shortlist"]
    if not mine:
        return {"text": "jev-skills: no shortlist yet in this session"}
    r = mine[-1]
    picks = ", ".join(f"{p['name']} {p['percent']}%" for p in r.get("picks", [])) or "none"
    failed = f"\nJev failed: {r['failed']}" if r.get("failed") else ""
    return {
        "text": f"Last shortlist ({r.get('scope')} scope): {picks}\n"
        f"prompt: {r.get('prompt', '')}\nroster {r.get('roster')} · Jev saw {r.get('asked')} · {r.get('calls')} call(s){failed}"
    }


def stats_mode(request: dict[str, Any]) -> dict[str, Any]:
    records = logs.read(logs.session_file(request["project_dir"], LOG_TOOL, str(request.get("session_id") or "")))
    lists = [r for r in records if r.get("kind") == "shortlist"]
    if not lists:
        return {"text": "jev-skills: nothing logged yet in this session"}
    loaded = [r for r in records if r.get("kind") == "loaded"]
    top = Counter(p["name"] for r in lists for p in r.get("picks", [])).most_common(5)
    activity = [
        ("Prompts judged", str(len(lists))),
        ("  with a shortlist", str(sum(1 for r in lists if r.get("picks")))),
        ("  Jev failures", str(sum(1 for r in lists if r.get("failed")))),
        ("Skills loaded", str(len(loaded))),
        ("  from a shortlist", str(sum(1 for r in loaded if r.get("shortlisted")))),
    ]
    blocks = [report.table("Activity", ("Metric", "Value"), activity, right=(1,))]
    if top:
        blocks.append(report.table("Most shortlisted", ("Skill", "Times"), [(n, str(c)) for n, c in top], right=(1,)))
    cost, notes = _cost(request, lists)
    return {"text": report.render(*blocks, cost, notes=notes)}


def _tokens(text: str) -> int:
    return len(text) // 4


def _cost(request: dict[str, Any], lists: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """The built-in skill listing, re-sent with every request, vs. Jev's shortlist notes and calls."""
    project, session_id = request["project_dir"], str(request.get("session_id") or "")
    roster = index.load(project, _config(request).is_global)
    claude = pricing.claude_log(project, session_id)
    model = pricing.main_model(claude)
    turns = len(pricing.main_turns(claude))
    price_in = pricing.rates(model)[0] / 1e6
    listing = sum(_tokens(f"- {s.name}: {s.description}") for s in roster)
    # Listing: written to the cache once, then read on every main-loop request.
    builtin = listing * price_in * (pricing.CACHE_WRITE + max(0, turns - 1) * pricing.CACHE_READ)
    described = {s.name: s.description for s in roster}
    note = sum(
        _tokens("optim-jev skill picker (Jev) shortlisted these skills for this request:")
        + sum(_tokens(f"- {p['name']} ({p['percent']}%): {described.get(p['name'], '')}") for p in r.get("picks", []))
        for r in lists
    )
    # A note is new text in each prompt: written to the cache once, then read by the turns after it.
    notes = note * price_in * pricing.CACHE_WRITE
    _, jev_in, jev_usd = pricing.jev_cost(lists)
    net = builtin - notes - jev_usd
    usd = pricing.usd
    cost = report.table(
        f"Cost: {turns} turn(s), {len(roster)} skill(s) in scope, vs the built-in skill list",
        ("Item", "Tokens", "Basis", "USD"),
        [
            ("Built-in skill list", f"~{listing:,}/req", "est.", usd(builtin)),
            ("Shortlist notes", f"~{note:,}", "est.", usd(notes)),
            ("Jev", f"{jev_in:,}", "measured", usd(jev_usd)),
        ],
        right=(1, 3),
        total=(report.net_label(net), "", "", usd(abs(net))),
    )
    return cost, [
        "Sizes estimated from the skill index at 4 characters a token; old notes re-read later are left out.",
        pricing.PRICE_NOTE,
    ]


HANDLERS = {"index": index_mode, "shortlist": shortlist_mode, "loaded": loaded_mode, "why": why_mode, "stats": stats_mode}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in HANDLERS:
        sys.exit(f"usage: python -m optim_jev.tools.jev_skills.tool {{{'|'.join(HANDLERS)}}}")
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    request.setdefault("project_dir", os.getcwd())
    sys.stdout.buffer.write(json.dumps(HANDLERS[mode](request), ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
