"""The one decision: which model a subagent runs on, judged by Jev from the prompt its parent wrote."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..jev_compacter.types import JevAsker, JevCompactionError, JevQuestions
from .catalog import Ladder
from .render import rule_rows
from .rules import Rule, Rules, relative, resolve

# Path-like tokens in a prompt: something with a slash, or a name with an extension.
_PATH = re.compile(r"[\w.@~-]*[\\/][\w.@~/\\-]+|[\w.@-]+\.[A-Za-z][\w]{0,7}\b")
MAX_PROMPT_CHARS = 6000


def choice_probabilities(answers: Mapping[str, Any], name: str, options: Sequence[str]) -> dict[str, float]:
    """A `choice` answer's probabilities over `options`, normalised; raises on anything malformed."""
    answer = answers.get(name)
    raw = answer.get("probabilities") if isinstance(answer, dict) else None
    if not isinstance(raw, dict):
        raise JevCompactionError(f"Invalid Jev answer for {name}")
    probs: dict[str, float] = {}
    for option in options:
        value = raw.get(option, 0.0)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise JevCompactionError(f"Invalid Jev probability for {name}/{option}")
        probs[option] = max(0.0, float(value))
    total = sum(probs.values())
    if total <= 0:
        raise JevCompactionError(f"Jev gave no probability for {name}")
    return {k: round(v / total, 3) for k, v in sorted(probs.items(), key=lambda kv: -kv[1])}


@dataclass(frozen=True)
class FilePlan:
    path: str
    rule: Rule | None


@dataclass(frozen=True)
class Pick:
    model: str
    source: str  # jev | rules | fallback
    files: tuple[FilePlan, ...]
    blocked: tuple[FilePlan, ...]
    allowed: tuple[str, ...]
    escalated: int = 0
    probabilities: dict[str, float] = field(default_factory=dict)
    jev_failed: str | None = None


def mentioned_files(text: str, rules: Rules, project_dir: str) -> list[FilePlan]:
    """Project paths the prompt names: existing files or directories, or paths under a rule."""
    root = Path(project_dir)
    found: dict[str, FilePlan] = {}
    for token in _PATH.findall(text):
        token = token.strip(".,:;'\"`()[]{}<>")
        if not token or "://" in token:
            continue
        rel = relative(token, project_dir).rstrip("/")
        if not rel or rel.startswith("../") or rel in found:
            continue
        rule = resolve(rules, rel)
        if rule is not None or (root / rel).exists():
            found[rel] = FilePlan(rel, rule)
    return list(found.values())


def _allowed(files: Sequence[FilePlan], ladder: Ladder) -> tuple[str, ...]:
    allowed = set(ladder.aliases)
    for f in files:
        if f.rule is not None:
            allowed &= set(f.rule.write)
    if not allowed and files:
        # Conflicting rules: the strongest model any of them allows.
        union = {a for f in files if f.rule for a in f.rule.write}
        allowed = {max(union, key=ladder.tier)} if union else set(ladder.aliases)
    return tuple(a for a in ladder.aliases if a in allowed)


def _bump(alias: str, by: int, ladder: Ladder) -> str:
    up = ladder.ascending
    return up[min(len(up) - 1, up.index(alias) + by)] if alias in up and by > 0 else alias


def _fallback(options: tuple[str, ...], ladder: Ladder) -> str:
    return ladder.current if ladder.current in options else max(options, key=ladder.tier)


def pick(
    description: str,
    prompt: str,
    rules: Rules,
    context: list[str],
    ladder: Ladder,
    asker: JevAsker,
    project_dir: str,
    escalated: Mapping[str, int] | None = None,
) -> Pick:
    """`context`: RULES.md lines for the files the prompt names. `escalated`: file -> levels to move up."""
    planned = mentioned_files(f"{description}\n{prompt}", rules, project_dir)
    writable = tuple(f for f in planned if f.rule is None or f.rule.write)
    blocked = tuple(f for f in planned if f.rule is not None and not f.rule.write)
    allowed = _allowed(writable, ladder)
    options = ladder.within_cap(allowed)
    boost = max((n for p, n in (escalated or {}).items() if any(f.path == p for f in planned)), default=0)

    if len(options) == 1:
        model, source, probs, failed = options[0], "rules", {}, None
    else:
        state = {
            "subagent_task": description,
            "subagent_prompt": prompt[:MAX_PROMPT_CHARS],
            "files": [{"path": f.path, "rule": f.rule.path if f.rule else None, "why": f.rule.why if f.rule else ""} for f in writable],
            "codebase_context": context,
            "models": [{"model": m.alias, "good_at": m.good_at, "relative_cost": m.cost} for m in ladder.models],
        }
        questions: JevQuestions = {
            "model": {
                "type": "choice",
                "instructions": (
                    "A subagent will carry out this prompt on its own. Pick the least capable model that will "
                    "do it correctly end to end. A stronger model than needed wastes money; a weaker one writes "
                    "wrong code."
                ),
                "criteria": {a: (ladder.info(a).good_at if ladder.info(a) else None) for a in options},
            }
        }
        try:
            probs = choice_probabilities(asker.ask(state, questions)["answers"], "model", options)
            model, source, failed = next(iter(probs)), "jev", None
        except JevCompactionError as err:
            model, source, probs, failed = _fallback(options, ladder), "fallback", {}, str(err)
    return Pick(_bump(model, boost, ladder), source, writable, blocked, allowed, boost, probs, failed)


def appendix(result: Pick, context: list[str], ladder: Ladder) -> str:
    """Text added to the subagent's prompt: its model, the rules and context of its files."""
    rows = list({f.rule.path: f.rule for f in (*result.files, *result.blocked) if f.rule}.values())
    lines = []
    if rows:
        lines += ["Routing rules for the files in this task:", *rule_rows(rows, ladder)]
    if context:
        lines += ["Codebase context (RULES.md):", *context]
    if result.blocked:
        lines.append("Never edit: " + ", ".join(f.path for f in result.blocked) + " (no model may).")
    if not lines:
        return ""
    return "\n\n---\noptim-jev router: you run on " + result.model + ".\n" + "\n".join(lines)


def toast(description: str, result: Pick) -> str:
    up = f" (⬆ {result.escalated} after errors)" if result.escalated else ""
    via = {"rules": " · by rules", "fallback": " · Jev offline"}.get(result.source, "")
    return f"jev · {description or 'subagent'} → {result.model}{up}{via}"


def files_json(files: Sequence[FilePlan]) -> list[dict[str, Any]]:
    return [{"path": f.path, "rule": f.rule.path if f.rule else None, "why": f.rule.why if f.rule else ""} for f in files]

