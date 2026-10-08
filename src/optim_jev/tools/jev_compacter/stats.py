"""`/jev-compact stats`: this session's compactions, Jev pruning vs. Claude Code's built-in summary."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...core import pricing

# Used only until this session has run a built-in summary of its own to measure.
FALLBACK_OUTPUT_RATIO = 0.10  # summary output tokens / context tokens
FALLBACK_KEEP_RATIO = 0.10  # context after / before


def _summary_shape(summaries: list[dict[str, Any]]) -> tuple[float, float, bool]:
    """(output ratio, keep ratio, measured?) from this session's built-in summaries."""
    sized = [s for s in summaries if s.get("tokens_before")]
    if not sized:
        return FALLBACK_OUTPUT_RATIO, FALLBACK_KEEP_RATIO, False
    before = sum(s["tokens_before"] for s in sized)
    out = sum(s.get("output_tokens", 0) for s in sized) / before
    kept = sum(s.get("tokens_after") or 0 for s in sized) / before
    return out, kept, True


def report(compactions: list[dict[str, Any]], claude: list[dict[str, Any]]) -> str:
    if not compactions:
        return "jev-compacter: no compaction yet in this session"
    model = pricing.main_model(claude)
    summaries = [r for r in claude if r.get("kind") == "summary" and r.get("agent_id") is None]
    turns = pricing.main_turns(claude)
    actions = Counter(c.get("action") for c in compactions)
    requests, jev_in, jev_usd = pricing.jev_cost(compactions)
    out_ratio, keep_ratio, measured = _summary_shape(summaries)
    cache_read = pricing.rates(model)[0] * pricing.CACHE_READ / 1e6  # USD per token

    lines = [
        f"Compactions: {len(compactions)} · applied {actions['apply']} · deferred {actions['defer']} · "
        f"fell back to summary {actions['summarize']}",
        f"Jev: {requests} request(s) · {jev_in:,} input tokens · {pricing.usd(jev_usd)}",
    ]
    if summaries:
        spent = sum(pricing.cost(s) for s in summaries)
        lines.append(
            f"Built-in summaries run: {len(summaries)} · {pricing.usd(spent)} measured · "
            f"output {out_ratio:.1%} of context · kept {keep_ratio:.1%} of context"
        )
    wasted = sum(c["jev"].get("cost_usd", 0.0) for c in compactions if c.get("action") == "summarize" and c.get("jev"))
    if wasted:
        lines.append(f"Jev spend on rounds that still fell back to the summary: {pricing.usd(wasted)}")

    applied = [c for c in compactions if c.get("action") == "apply"]
    if applied:
        bounds = sorted(r["ts"] for r in (*compactions, *summaries))
        summary_usd = jev_side = extra_after = 0.0
        for c in applied:
            used = c.get("used_tokens", 0)
            summary_usd += pricing.cost({"cache_read_input_tokens": used, "output_tokens": round(used * out_ratio)}, model)
            jev_side += (c.get("jev") or {}).get("cost_usd", 0.0)
            left_jev = max(0, used - c.get("freed_tokens_est", 0))
            extra_tokens = left_jev - used * keep_ratio
            end = next((t for t in bounds if t > c["ts"]), float("inf"))
            after = sum(1 for t in turns if c["ts"] < t["ts"] <= end)
            extra_after += after * extra_tokens * cache_read
        net = summary_usd - jev_side - extra_after
        basis = "this session's measured summaries" if measured else "assumed 10% output / 10% kept (no summary measured yet)"
        lines += [
            "",
            f"Applied Jev prunes vs. a built-in summary in their place ({basis}):",
            f"  summary (est.)                 {pricing.usd(summary_usd)}",
            f"  Jev (measured)                 {pricing.usd(jev_side)}",
            f"  larger context re-read after   {pricing.usd(extra_after)}  (est., cache reads until the next compaction)",
            f"  net {'saved' if net >= 0 else 'extra'}                      {pricing.usd(abs(net))}",
        ]
    lines += ["", pricing.PRICE_NOTE]
    return "\n".join(lines)
