from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping

from ..jev_compacter.config import DEFAULT_MODEL, SYSTEM_ONE_URL


@dataclass(frozen=True)
class SkillsConfig:
    # project: .claude/skills only. global: also ~/.claude/skills and installed plugins' skills.
    scope: str = "project"
    max_picks: int = 3
    # A skill is shortlisted only at or above this share of Jev's final choice, and above "none".
    min_percent: int = 30
    batch_size: int = 20
    # Above this many skills, a keyword pre-filter cuts the field before Jev sees it.
    prefilter_above: int = 40
    # Cap on one shortlist request to Jev (state and candidate skills).
    max_input_tokens: int = 3000
    model: str = DEFAULT_MODEL
    base_url: str = SYSTEM_ONE_URL

    @property
    def is_global(self) -> bool:
        return self.scope == "global"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SkillsConfig:
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            default = getattr(defaults, f.name)
            raw = values.get(f.name)
            if isinstance(default, str):
                kwargs[f.name] = str(raw or default)
            else:
                kwargs[f.name] = max(1, math.floor(_number(raw, default)))
        return cls(**kwargs)


def _number(value: Any, fallback: float) -> float:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return fallback
