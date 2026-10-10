"""The shortlist: Jev scores the roster in batches, then once more over each batch's best.

Probabilities are only comparable inside one question, so round one keeps each batch's leaders
and round two ranks them together. Each question has a "none" option; a skill is shortlisted
only when it beats "none" and reaches the configured share.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ...core.budget import Field, Fitted, OverBudget, fit, middle, tokens_of
from ..jev_compacter.types import JevAsker, JevCompactionError
from ..jev_router.policy import choice_probabilities
from .config import SkillsConfig
from .index import Skill

NONE = "none"
NONE_CRITERION = (
    "No skill fits: a question, a small edit, a follow-up, or work none of the listed skills is for."
)
INSTRUCTIONS = (
    "Which skill, if any, holds the procedure this request needs? Pick a skill only when following "
    "it would clearly help; otherwise pick none."
)
LEADERS_PER_BATCH = 2
ROUND_ONE_FLOOR = 0.15
_WORD = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class Shortlist:
    picks: tuple[tuple[Skill, float], ...]
    asked: int  # skills Jev saw
    calls: int
    failed: str | None = None
    rounds: list[dict[str, float]] = field(default_factory=list)
    trimmed: bool = False


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def prefilter(prompt: str, roster: Sequence[Skill], keep: int) -> list[Skill]:
    """The `keep` skills whose name and description share the most words with the prompt."""
    words = _words(prompt)
    scored = sorted(roster, key=lambda s: -len(words & _words(f"{s.name} {s.description}")))
    return list(scored[:keep])


RECENT_INPUT_CHARS = 500


def _question(batch: Sequence[Skill]) -> dict:
    criteria = {s.name: s.description for s in batch}
    criteria[NONE] = NONE_CRITERION
    return {"skill": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}}


def _state(prompt: str, recent: Sequence[str], budget: int) -> Fitted:
    """The request, then the person's earlier prompts (oldest dropped first when over budget)."""
    fields = [
        Field("user_request", prompt[:4000], "middle"),
        Field("recent_user_inputs", [middle(t, RECENT_INPUT_CHARS) for t in recent if t.strip()], "drop_first"),
    ]
    return fit(fields, budget, overhead=tokens_of(_question([])))


def _batches(skills: Sequence[Skill], room: int, most: int) -> list[list[Skill]]:
    """Groups of at most `most` skills whose question fits in `room` tokens."""
    base = tokens_of(_question([]))
    batches: list[list[Skill]] = []
    current: list[Skill] = []
    used = base
    for skill in skills:
        cost = tokens_of({skill.name: skill.description})
        if base + cost > room:
            raise JevCompactionError(f"skill {skill.name} alone exceeds the Jev input budget")
        if current and (used + cost > room or len(current) >= most):
            batches.append(current)
            current, used = [], base
        current.append(skill)
        used += cost
    if current:
        batches.append(current)
    return batches


def _ask(asker: JevAsker, state: dict, batch: Sequence[Skill]) -> dict[str, float]:
    answers = asker.ask(state, _question(batch))["answers"]
    return choice_probabilities(answers, "skill", [*(s.name for s in batch), NONE])


def shortlist(
    prompt: str, recent: Sequence[str], roster: Sequence[Skill], asker: JevAsker, config: SkillsConfig
) -> Shortlist:
    """`recent`: the person's earlier prompts, oldest first; never Claude's replies or tool output."""
    candidates = list(roster)
    if len(candidates) > config.prefilter_above:
        candidates = prefilter(prompt, candidates, config.prefilter_above)
    if not candidates:
        return Shortlist((), 0, 0)
    by_name = {s.name: s for s in candidates}
    try:
        # The state goes with every batch; the batches share what is left of the budget.
        fitted = _state(prompt, recent, config.max_input_tokens // 2)
        room = config.max_input_tokens - fitted.tokens + tokens_of(_question([]))
        batches = _batches(candidates, room, config.batch_size)
        with ThreadPoolExecutor(max_workers=min(8, len(batches))) as pool:
            first = list(pool.map(lambda b: _ask(asker, fitted.state, b), batches))
        rounds = list(first)
        if len(batches) == 1:
            final = first[0]
        else:
            ranked = sorted(
                (
                    (p, name)
                    for probs in first
                    for name, p in list((k, v) for k, v in probs.items() if k != NONE)[:LEADERS_PER_BATCH]
                    if p >= ROUND_ONE_FLOOR
                ),
                reverse=True,
            )
            if not ranked:
                return Shortlist((), len(candidates), len(batches), rounds=rounds)
            # The final round is one question: the strongest leaders that fit in it.
            leaders = _batches([by_name[n] for _, n in ranked], room, config.batch_size)[0]
            final = _ask(asker, fitted.state, leaders)
            rounds.append(final)
    except (JevCompactionError, OverBudget) as err:
        return Shortlist((), len(candidates), 0, str(err))
    bar = max(config.min_percent / 100, final.get(NONE, 0.0))
    picks = tuple((by_name[n], p) for n, p in final.items() if n != NONE and p >= bar)[: config.max_picks]
    return Shortlist(picks, len(candidates), len(rounds), rounds=rounds, trimmed=fitted.trimmed)
