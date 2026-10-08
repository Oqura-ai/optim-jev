"""USD prices for logged token counts, and the shared reading of the Claude usage log."""

from __future__ import annotations

import os
from typing import Any

from . import logs

# USD per million tokens: (input, output). Matched by family name inside the model id.
CLAUDE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}
CACHE_READ = 0.1  # x input price
CACHE_WRITE = 1.25  # x input price (5-minute cache)


def rates(model: str | None) -> tuple[float, float]:
    lowered = (model or "").lower()
    return next((r for family, r in CLAUDE_USD_PER_MTOK.items() if family in lowered), CLAUDE_USD_PER_MTOK["sonnet"])


def cost(record: dict[str, Any], model: str | None = None) -> float:
    """A usage record priced at `model` (default: the model that answered)."""
    inp, out = rates(model or record.get("model"))
    tokens = (
        record.get("input_tokens", 0) * inp
        + record.get("cache_read_input_tokens", 0) * inp * CACHE_READ
        + record.get("cache_creation_input_tokens", 0) * inp * CACHE_WRITE
        + record.get("output_tokens", 0) * out
    )
    return tokens / 1e6


def jev_cost(records: list[dict[str, Any]]) -> tuple[int, int, float]:
    """(requests, input tokens, USD) over the `jev` blocks of a tool's records."""
    blocks = [r["jev"] for r in records if isinstance(r.get("jev"), dict)]
    return (
        sum(b.get("requests", 0) for b in blocks),
        sum(b.get("input_tokens", 0) for b in blocks),
        sum(b.get("cost_usd", 0.0) for b in blocks),
    )


def claude_log(project_dir: str | os.PathLike[str], session_id: str) -> list[dict[str, Any]]:
    return logs.read(logs.session_file(project_dir, "claude", session_id))


def main_turns(claude: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in claude if r.get("kind") == "turn" and r.get("agent_id") is None]


def main_model(claude: list[dict[str, Any]]) -> str | None:
    turns = main_turns(claude)
    return turns[-1].get("model") if turns else None


def usd(value: float) -> str:
    return f"${value:.4f}" if abs(value) < 1 else f"${value:.2f}"


PRICE_NOTE = (
    "Prices: Claude list prices per 1M tokens (opus $5/$25, sonnet $3/$15, haiku $1/$5; cache read 0.1x, "
    "write 1.25x), Jev $0.04 input / $0 output. Edit core/pricing.py if yours differ."
)
