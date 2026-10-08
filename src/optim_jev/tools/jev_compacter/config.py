from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping

SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

_AT_LEAST_ONE = {"max_state_tokens", "max_request_tokens"}


@dataclass(frozen=True)
class CompactionConfig:
    # Jev pruning
    goal: str = ""
    keep_threshold: float = 0.5
    preserve_recent_messages: int = 6
    max_state_tokens: int = 25_000
    max_request_tokens: int = 30_000
    truncate_head_chars: int = 300
    # Re-ask Jev about a remembered call when either probability is this close to the threshold.
    reask_margin: float = 0.15
    model: str = DEFAULT_MODEL
    base_url: str = SYSTEM_ONE_URL

    # Policy, as percentages of the context window
    soft_percent: int = 60
    hard_percent: int = 85
    target_percent: int = 40
    # Context must grow this much since the last round before a soft or idle trigger fires.
    regrow_percent: int = 10
    # Below the target, a pruning is still applied when it frees at least this much.
    min_freed_tokens: int = 8_000
    # Prompt cache TTL: after this much idle time a rewrite costs no extra cache misses.
    cache_idle_seconds: int = 300

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> CompactionConfig:
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            default = getattr(defaults, f.name)
            raw = values.get(f.name)
            if isinstance(default, str):
                kwargs[f.name] = str(raw or default)
            elif isinstance(default, int):
                floor = 1 if f.name in _AT_LEAST_ONE else 0
                kwargs[f.name] = max(floor, math.floor(_number(raw, default)))
            else:
                kwargs[f.name] = _number(raw, default)
        return cls(**kwargs)


def _number(value: Any, fallback: float) -> float:
    # Plugin options arrive as strings when passed through the environment.
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return fallback
