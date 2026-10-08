"""The model ladder: `.optim-jev/jev_router/models.json` (written by init), narrowed for this session.

Until init has run, the built-in defaults stand. Init checks each model against the account
and records the id that worked, or `available: false`, so routing never names a model that fails.
The file stays local: ids and access are the account's, not the team's.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from .rules import router_dir, write_atomic

MODELS_FILE = "models.json"

DEFAULT_MODELS: tuple[dict[str, Any], ...] = (
    {"alias": "opus", "id": "claude-opus-5-5", "tier": 3, "cost": 5,
     "good_at": "cross-module design, subtle invariants, hard debugging"},
    {"alias": "sonnet", "id": "claude-sonnet-5-5", "tier": 2, "cost": 3,
     "good_at": "most feature work, refactors in known patterns"},
    {"alias": "haiku", "id": "claude-haiku-4-5-20251001", "tier": 1, "cost": 1,
     "good_at": "mechanical edits, tests, docs, renames"},
)


@dataclass(frozen=True)
class ModelInfo:
    alias: str
    tier: int
    cost: float
    good_at: str
    # Full API id a mid-turn switch names ("" = learn it from the engine at runtime).
    id: str = ""
    available: bool = True


@dataclass(frozen=True)
class Ladder:
    # Strongest first; unavailable and excluded models removed.
    models: tuple[ModelInfo, ...]
    current: str | None
    current_id: str
    capped: bool
    learned: dict[str, str] = field(default_factory=dict)

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(m.alias for m in self.models)

    @property
    def ascending(self) -> tuple[str, ...]:
        return tuple(reversed(self.aliases))

    def info(self, alias: str) -> ModelInfo | None:
        return next((m for m in self.models if m.alias == alias), None)

    def tier(self, alias: str) -> int:
        info = self.info(alias)
        return info.tier if info else 0

    def within_cap(self, aliases: tuple[str, ...]) -> tuple[str, ...]:
        """`aliases` limited to the session model's tier, or unchanged when that leaves none."""
        if not self.capped or self.current is None:
            return aliases
        ceiling = self.tier(self.current)
        kept = tuple(a for a in aliases if self.tier(a) <= ceiling)
        return kept or aliases


def _parse(raw: Any) -> tuple[ModelInfo, ...]:
    models = []
    for m in raw if isinstance(raw, list) else ():
        try:
            models.append(
                ModelInfo(
                    str(m["alias"]), int(m["tier"]), float(m["cost"]), str(m.get("good_at", "")),
                    str(m.get("id") or ""), m.get("available", True) is not False,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(models, key=lambda m: m.tier, reverse=True))


def load_catalog(project_dir: str | os.PathLike[str] | None = None) -> tuple[ModelInfo, ...]:
    if project_dir is not None:
        try:
            models = _parse(json.loads((router_dir(project_dir) / MODELS_FILE).read_text(encoding="utf-8")))
            if models:
                return models
        except (OSError, ValueError):
            pass
    return _parse(list(DEFAULT_MODELS))


def save_catalog(project_dir: str | os.PathLike[str], models: tuple[ModelInfo, ...]) -> None:
    write_atomic(
        router_dir(project_dir) / MODELS_FILE,
        json.dumps([asdict(m) for m in models], indent=2, ensure_ascii=False) + "\n",
    )


def with_checks(catalog: tuple[ModelInfo, ...], checks: Any) -> tuple[ModelInfo, ...]:
    """The catalog after init's access check: `{alias: {"id": str, "available": bool}}`."""
    if not isinstance(checks, dict):
        return catalog
    out = []
    for m in catalog:
        check = checks.get(m.alias)
        if isinstance(check, dict):
            m = ModelInfo(
                m.alias, m.tier, m.cost, m.good_at,
                str(check.get("id") or ""), check.get("available", True) is not False,
            )
        out.append(m)
    return tuple(out)


def alias_of(model_id: str, catalog: tuple[ModelInfo, ...]) -> str | None:
    lowered = model_id.lower()
    return next((m.alias for m in catalog if m.alias in lowered), None)


def build_ladder(
    session_model: str,
    exclude: tuple[str, ...] = (),
    capped: bool = True,
    learned: dict[str, str] | None = None,
    project_dir: str | os.PathLike[str] | None = None,
) -> Ladder:
    catalog = load_catalog(project_dir)
    current = alias_of(session_model, catalog)
    models = tuple(
        m for m in catalog if m.alias == current or (m.available and m.alias not in exclude)
    )
    return Ladder(models, current, session_model, capped, dict(learned or {}))
