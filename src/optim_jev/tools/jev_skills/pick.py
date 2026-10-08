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


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def prefilter(prompt: str, roster: Sequence[Skill], keep: int) -> list[Skill]:
    """The `keep` skills whose name and description share the most words with the prompt."""
    words = _words(prompt)
    scored = sorted(roster, key=lambda s: -len(words & _words(f"{s.name} {s.description}")))
    return list(scored[:keep])


def _ask(asker: JevAsker, prompt: str, previous: str, batch: Sequence[Skill]) -> dict[str, float]:
    criteria = {s.name: s.description for s in batch}
    criteria[NONE] = NONE_CRITERION
    state = {"user_request": prompt[:4000], "previous_assistant_message": previous[:1500]}
    answers = asker.ask(state, {"skill": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": criteria}})["answers"]
    return choice_probabilities(answers, "skill", list(criteria))


def shortlist(prompt: str, previous: str, roster: Sequence[Skill], asker: JevAsker, config: SkillsConfig) -> Shortlist:
    candidates = list(roster)
    if len(candidates) > config.prefilter_above:
        candidates = prefilter(prompt, candidates, config.prefilter_above)
    if not candidates:
        return Shortlist((), 0, 0)
    by_name = {s.name: s for s in candidates}
    batches = [candidates[i : i + config.batch_size] for i in range(0, len(candidates), config.batch_size)]
    try:
        with ThreadPoolExecutor(max_workers=min(8, len(batches))) as pool:
            first = list(pool.map(lambda b: _ask(asker, prompt, previous, b), batches))
        rounds = list(first)
        if len(batches) == 1:
            final = first[0]
        else:
            leaders = [
                name
                for probs in first
                for name, p in list((k, v) for k, v in probs.items() if k != NONE)[:LEADERS_PER_BATCH]
                if p >= ROUND_ONE_FLOOR
            ]
            if not leaders:
                return Shortlist((), len(candidates), len(batches), rounds=rounds)
            final = _ask(asker, prompt, previous, [by_name[n] for n in leaders])
            rounds.append(final)
    except JevCompactionError as err:
        return Shortlist((), len(candidates), len(batches), str(err))
    bar = max(config.min_percent / 100, final.get(NONE, 0.0))
    picks = tuple((by_name[n], p) for n, p in final.items() if n != NONE and p >= bar)[: config.max_picks]
    return Shortlist(picks, len(candidates), len(rounds), rounds=rounds)
