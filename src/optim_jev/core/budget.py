"""Caps what goes to Jev: a state's fields are listed most important first, and trimming starts at the end.

A field is shrunk only as far as needed, then the next one up. Fields marked `keep` are never touched;
when they alone exceed the budget, `fit` raises OverBudget and the caller falls back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

# The compacter's tokenizer-free estimate; one shared rule keeps every tool's numbers comparable.
from ..tools.jev_compacter.state import estimate_tokens

Shrink = Literal["keep", "middle", "drop_first", "drop_last"]
MIN_TEXT_CHARS = 200


class OverBudget(Exception):
    def __init__(self, tokens: int, budget: int) -> None:
        super().__init__(f"Jev input ~{tokens} tokens even after trimming; budget {budget}")
        self.tokens = tokens
        self.budget = budget


@dataclass
class Field:
    key: str
    value: Any
    shrink: Shrink = "keep"


@dataclass(frozen=True)
class Fitted:
    state: dict[str, Any]
    tokens: int
    trimmed: bool


def tokens_of(value: Any) -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def middle(text: str, chars: int) -> str:
    if len(text) <= chars:
        return text
    head = chars * 2 // 3
    return f"{text[:head]} […] {text[len(text) - (chars - head):]}"


def _step(field: Field) -> bool:
    """Shrinks one step; False when nothing more can go."""
    v = field.value
    if field.shrink == "middle" and isinstance(v, str) and len(v) > MIN_TEXT_CHARS:
        field.value = middle(v, max(MIN_TEXT_CHARS, len(v) * 2 // 3))
        return True
    if field.shrink in ("drop_first", "drop_last") and isinstance(v, list) and v:
        field.value = v[1:] if field.shrink == "drop_first" else v[:-1]
        return True
    return False


def fit(fields: list[Field], budget: int, overhead: int = 0) -> Fitted:
    """`fields` most important first; `overhead`: tokens the questions add beside the state."""

    def state() -> dict[str, Any]:
        return {f.key: f.value for f in fields if f.value not in (None, "", [], {})}

    trimmed = False
    total = tokens_of(state()) + overhead
    for field in reversed(fields):
        while total > budget and _step(field):
            trimmed = True
            total = tokens_of(state()) + overhead
    if total > budget:
        raise OverBudget(total, budget)
    return Fitted(state(), total, trimmed)
