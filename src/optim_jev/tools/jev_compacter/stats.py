"""`/jev-compact stats`: this session's compactions, Jev pruning vs. Claude Code's built-in summary."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ...core import pricing
from ...core import report as fmt

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

    usd = pricing.usd
    spent = sum(pricing.cost(s) for s in summaries)
    wasted = sum(c["jev"].get("cost_usd", 0.0) for c in compactions if c.get("action") == "summarize" and c.get("jev"))
    activity = [
        ("Compactions", str(len(compactions))),
        ("  applied", str(actions["apply"])),
        ("  deferred", str(actions["defer"])),
        ("  fell back to summary", str(actions["summarize"])),
        ("Jev requests", str(requests)),
        ("Jev input tokens", f"{jev_in:,}"),
        ("Jev cost", usd(jev_usd)),
    ]
    if summaries:
        activity += [
            ("Built-in summaries run", str(len(summaries))),
            ("  their cost", usd(spent)),
            ("  output, % of context", f"{out_ratio:.1%}"),
            ("  context kept", f"{keep_ratio:.1%}"),
        ]
    if wasted:
        activity.append(("Jev cost on fallbacks", usd(wasted)))
    blocks = [fmt.table("Activity", ("Metric", "Value"), activity, right=(1,))]
    notes = []

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
        blocks.append(
            fmt.table(
                f"Cost: {len(applied)} applied prune(s) vs a built-in summary in their place",
                ("Item", "Basis", "USD"),
                [
                    ("Built-in summary", "est.", usd(summary_usd)),
                    ("Jev pruning", "measured", usd(jev_side)),
                    ("Larger context re-read", "est.", usd(extra_after)),
                ],
                right=(2,),
                total=(fmt.net_label(net), "", usd(abs(net))),
            )
        )
        notes.append(
            "Summary size measured from this session's own summaries."
            if measured
            else "No summary measured yet: assumed 10% output and 10% of context kept."
        )
        notes.append("Re-read: the extra context Jev leaves, as cache reads until the next compaction.")
    notes.append(pricing.PRICE_NOTE)
    return fmt.render(*blocks, notes=notes)
