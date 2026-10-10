"""The one decision: which model a subagent runs on, judged by Jev from the prompt its parent wrote."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..jev_compacter.types import JevAsker, JevCompactionError, JevQuestions
from ...core.budget import Field, OverBudget, fit, middle, tokens_of
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
    source: str  # jev | rules | escalation | claude | fallback
    files: tuple[FilePlan, ...]
    blocked: tuple[FilePlan, ...]
    allowed: tuple[str, ...]
    escalated: int = 0
    probabilities: dict[str, float] = field(default_factory=dict)
    jev_failed: str | None = None
    # None: the session's default effort (Jev offline, or a model without effort).
    effort: str | None = None
    effort_probabilities: dict[str, float] = field(default_factory=dict)
    input_tokens_est: int = 0
    trimmed: bool = False
    # Set when Jev's input stays over budget after trimming: the prompt for Claude to decide instead.
    ask_claude: str | None = None


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


EFFORTS = ("low", "medium", "high")
EFFORT_CRITERIA = {
    "low": "mechanical or well-specified: renames, small fixes, docs, boilerplate",
    "medium": "ordinary feature work in a known pattern",
    "high": "needs planning across files, or subtle logic",
    "xhigh": "hard design or debugging where getting it wrong is costly",
}
RECENT_INPUT_CHARS = 500
MODEL_INSTRUCTIONS = (
    "A subagent will carry out this prompt on its own. Pick the least capable model that will do it "
    "correctly end to end. A stronger model than needed wastes money; a weaker one writes wrong code."
)
EFFORT_INSTRUCTIONS = (
    "How hard should that subagent think? Pick the lowest effort that will still get it right; more "
    "effort costs more tokens."
)


def efforts_for(model: str) -> tuple[str, ...]:
    return (*EFFORTS, "xhigh") if model == "opus" else EFFORTS


def _clamp(effort: str | None, model: str) -> str | None:
    if effort is None:
        return None
    return effort if effort in efforts_for(model) else "high"


def _escalation(escalated: Mapping[str, Any] | None, planned: Sequence[FilePlan]) -> tuple[int, str | None]:
    """Levels to move up and the effort to keep, from the most escalated file this task names."""
    best, effort = 0, None
    for path, entry in (escalated or {}).items():
        if not any(f.path == path for f in planned):
            continue
        levels = entry.get("levels", 0) if isinstance(entry, Mapping) else entry
        if isinstance(levels, int) and levels > best:
            best = levels
            raw = entry.get("effort") if isinstance(entry, Mapping) else None
            effort = raw if isinstance(raw, str) else None
    return best, effort


def _fields(description: str, prompt: str, writable: Sequence[FilePlan], context: list[str],
            ladder: Ladder, recent: Sequence[str]) -> list[Field]:
    """Jev's state, most important first; budget trimming starts at the bottom."""
    files = []
    for f in writable:
        entry: dict[str, Any] = {"path": f.path}
        if f.rule is not None and f.rule.why:
            entry["why"] = f.rule.why
        files.append(entry)
    return [
        Field("subagent_task", description),
        Field("files", files),
        Field("models", [{"model": m.alias, "good_at": m.good_at, "relative_cost": m.cost} for m in ladder.models]),
        Field("subagent_prompt", prompt[:MAX_PROMPT_CHARS], "middle"),
        Field("codebase_context", list(context), "drop_last"),
        Field("recent_user_inputs", [middle(t, RECENT_INPUT_CHARS) for t in recent if t.strip()], "drop_first"),
    ]


def _claude_prompt(fields: list[Field], questions: JevQuestions) -> str:
    """For when Jev's input stays over budget: Claude reads the same state, untrimmed, and answers JSON."""
    state = json.dumps({f.key: f.value for f in fields if f.value}, ensure_ascii=False, indent=1)
    asks = "\n".join(
        f'- "{k}": one of {", ".join(q["criteria"])}. {q["instructions"]}' for k, q in questions.items()
    )
    keys = ", ".join(f'"{k}": "..."' for k in questions)
    return (
        "You route a coding subagent to a model. Task and context:\n"
        + middle(state, 60_000)
        + "\n\nAnswer these:\n"
        + asks
        + "\n\nReply with only a JSON object: {"
        + keys
        + "}"
    )


def pick(
    description: str,
    prompt: str,
    rules: Rules,
    context: list[str],
    ladder: Ladder,
    asker: JevAsker,
    project_dir: str,
    escalated: Mapping[str, Any] | None = None,
    recent: Sequence[str] = (),
    budget: int = 4000,
    decided: Mapping[str, Any] | None = None,
) -> Pick:
    """`context`: RULES.md lines for the files the prompt names. `escalated`: file -> {levels, effort}
    (or a bare level count). `recent`: the person's last prompts, oldest first. `decided`: Claude's
    answer when Jev's input was over budget ({"model", "effort"})."""
    planned = mentioned_files(f"{description}\n{prompt}", rules, project_dir)
    writable = tuple(f for f in planned if f.rule is None or f.rule.write)
    blocked = tuple(f for f in planned if f.rule is not None and not f.rule.write)
    allowed = _allowed(writable, ladder)
    options = ladder.within_cap(allowed)
    boost, kept_effort = _escalation(escalated, planned)

    def done(model: str, source: str, **kw: Any) -> Pick:
        final = _bump(model, boost, ladder)
        effort = kw.pop("effort", None)
        # After an escalation the model moves up one and the effort stays what it was.
        effort = kept_effort if kept_effort is not None else effort
        return Pick(final, source, writable, blocked, allowed, boost, effort=_clamp(effort, final), **kw)

    questions: JevQuestions = {}
    if len(options) > 1:
        questions["model"] = {
            "type": "choice",
            "instructions": MODEL_INSTRUCTIONS,
            "criteria": {a: (ladder.info(a).good_at if ladder.info(a) else None) for a in options},
        }
    if kept_effort is None:
        # xhigh is offered only when opus can be the answer.
        efforts = (*EFFORTS, "xhigh") if "opus" in options else EFFORTS
        questions["effort"] = {
            "type": "choice",
            "instructions": EFFORT_INSTRUCTIONS,
            "criteria": {e: EFFORT_CRITERIA[e] for e in efforts},
        }

    if decided is not None and decided.get("failed"):
        return done(_fallback(options, ladder), "fallback", jev_failed=str(decided["failed"]))
    if decided is not None:
        model = decided.get("model") if decided.get("model") in options else _fallback(options, ladder)
        effort = decided.get("effort") if decided.get("effort") in EFFORT_CRITERIA else None
        return done(model, "claude", effort=effort)
    if not questions:
        return done(options[0], "escalation" if boost else "rules")

    fields = _fields(description, prompt, writable, context, ladder, recent)
    try:
        fitted = fit(fields, budget, overhead=tokens_of(questions))
    except OverBudget as err:
        return done(
            _fallback(options, ladder), "fallback", jev_failed=str(err), ask_claude=_claude_prompt(fields, questions)
        )
    try:
        answers = asker.ask(fitted.state, questions)["answers"]
        probs = choice_probabilities(answers, "model", options) if "model" in questions else {}
    except JevCompactionError as err:
        return done(
            _fallback(options, ladder), "fallback", jev_failed=str(err),
            input_tokens_est=fitted.tokens, trimmed=fitted.trimmed,
        )
    effort_probs: dict[str, float] = {}
    if "effort" in questions:
        try:
            effort_probs = choice_probabilities(answers, "effort", list(questions["effort"]["criteria"]))
        except JevCompactionError:
            pass  # a bad effort answer costs only the effort: the session default stands
    model = next(iter(probs)) if probs else options[0]
    source = "jev" if probs else ("escalation" if boost else "rules")
    return done(
        model, source, effort=next(iter(effort_probs), None), probabilities=probs,
        effort_probabilities=effort_probs, input_tokens_est=fitted.tokens, trimmed=fitted.trimmed,
    )


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
    on = result.model + (f" at {result.effort} effort" if result.effort else "")
    return "\n\n---\noptim-jev router: you run on " + on + ".\n" + "\n".join(lines)


def toast(description: str, result: Pick) -> str:
    up = f" (⬆ {result.escalated} after errors)" if result.escalated else ""
    via = {"rules": " · by rules", "fallback": " · Jev offline", "claude": " · decided by Claude"}.get(result.source, "")
    effort = f" · {result.effort}" if result.effort else ""
    return f"jev · {description or 'subagent'} → {result.model}{effort}{up}{via}"


def files_json(files: Sequence[FilePlan]) -> list[dict[str, Any]]:
    return [{"path": f.path, "rule": f.rule.path if f.rule else None, "why": f.rule.why if f.rule else ""} for f in files]

