"""Text the router puts in front of models: the main loop's prompt section and rules rows.

The section is the delegation instruction and the model ladder only, the same every turn so the
prompt cache keeps it; rules and codebase context go into each subagent's prompt instead.
"""

from __future__ import annotations

from .catalog import Ladder
from .rules import Rule

INSTRUCTION = (
    "You cannot edit, write or delete files yourself; those calls are refused. Make every file change "
    "through the Agent tool. Jev, a model router, reads each subagent's prompt and runs it on the "
    "cheapest model that will do it correctly, so write prompts that stand alone: the goal, the exact "
    "file paths to change, and what done looks like. Give unrelated changes their own subagents so "
    "simple ones go to cheaper models. Reading, searching and running commands stay with you."
)


def models_label(models: tuple[str, ...], ladder: Ladder) -> str:
    if not models:
        return "none"
    ascending = ladder.ascending
    if set(models) >= set(ascending):
        return "any"
    lowest = min(models, key=ladder.tier)
    upward = tuple(a for a in ascending if ladder.tier(a) >= ladder.tier(lowest))
    if set(models) == set(upward):
        return lowest if len(upward) == 1 else f"{lowest}+"
    return "+".join(a for a in ascending if a in models)


def ladder_lines(ladder: Ladder) -> list[str]:
    def name(alias: str) -> str:
        return f"{alias} ({ladder.current_id}, current)" if alias == ladder.current else alias

    costs = ":".join(f"{m.cost:g}" for m in ladder.models)
    lines = [f"models: {' > '.join(name(a) for a in ladder.aliases)} · relative cost {costs}"]
    for m in ladder.models:
        learned = ladder.learned.get(m.alias)
        lines.append(f"- {m.alias}: {m.good_at}" + (f" · {learned}" if learned else ""))
    return lines


def section(ladder: Ladder) -> str:
    return "\n".join(["## optim-jev model router", INSTRUCTION, "", *ladder_lines(ladder)])


def rule_rows(rows: list[Rule], ladder: Ladder) -> list[str]:
    """One aligned line per rule: path, models allowed to write, why."""
    if not rows:
        return []
    width = max(len(r.path) for r in rows)
    labels = {r.path: models_label(r.write, ladder) for r in rows}
    lwidth = max(len(v) for v in labels.values())
    lines = []
    for r in rows:
        why = " ".join(
            p for p in (r.why, "" if r.delete == r.write else f"(delete: {models_label(r.delete, ladder)})") if p
        )
        lines.append(f"{r.path.ljust(width)}  {labels[r.path].ljust(lwidth)}  {why}".rstrip())
    return lines
