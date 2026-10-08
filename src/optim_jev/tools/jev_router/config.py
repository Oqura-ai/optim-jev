from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Mapping

from ..jev_compacter.config import DEFAULT_MODEL, SYSTEM_ONE_URL


@dataclass(frozen=True)
class RouterConfig:
    # Jev never picks a model above the session's (rules still win).
    cap: str = "on"
    depth: int = 2
    model: str = DEFAULT_MODEL
    base_url: str = SYSTEM_ONE_URL

    @property
    def is_capped(self) -> bool:
        return self.cap != "off"

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> RouterConfig:
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            default = getattr(defaults, f.name)
            raw = values.get(f.name)
            if isinstance(default, str):
                kwargs[f.name] = str(raw or default)
            else:
                kwargs[f.name] = max(0, math.floor(_number(raw, default)))
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
