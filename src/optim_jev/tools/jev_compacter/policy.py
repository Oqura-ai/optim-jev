from __future__ import annotations

from collections.abc import Sequence

from .config import CompactionConfig
from .logic import compact, message_tokens
from .types import (
    CallAnswer,
    CompactionMemory,
    CompactResult,
    ContextUsage,
    JevAsker,
    JevCompactionError,
    Message,
    PolicyAction,
    PolicyOutcome,
    TriggerLevel,
)


def trigger_level(
    usage: ContextUsage, memory: CompactionMemory, config: CompactionConfig
) -> TriggerLevel | None:
    if usage.percent >= config.hard_percent:
        return "hard"
    regrow = config.regrow_percent / 100 * usage.window_tokens
    baseline = memory.baseline_tokens
    # Context below the baseline means it shrank outside this tool (e.g. /compact): stale.
    if baseline is not None and baseline <= usage.used_tokens < baseline + regrow:
        return None
    if usage.percent >= config.soft_percent:
        return "soft"
    if usage.idle_seconds >= config.cache_idle_seconds and usage.percent > config.target_percent:
        return "idle"
    return None


def _k(tokens: int) -> str:
    return f"~{tokens / 1000:.1f}k tokens" if tokens >= 1000 else f"~{tokens} tokens"


def _verdict(result: CompactResult) -> str:
    """What Jev decided, independent of how many tokens it frees."""
    s = result.stats
    candidates = s.calls - s.pinned
    if candidates == 0:
        return f"no tool calls to judge ({s.pinned} pinned)" if s.pinned else "no tool calls to judge"
    changed = [
        f"{label} {count}"
        for count, label in ((s.calls_dropped, "dropped"), (s.results_dropped, "truncated"))
        if count
    ]
    if not changed:
        return f"Jev kept all {candidates} tool calls"
    return f"Jev {', '.join(changed)}, kept {s.kept} of {candidates} tool calls"


def _surviving(result: CompactResult) -> dict[str, CallAnswer]:
    present = {t.tool_use_id for m in result.messages for t in m.tool_uses}
    return {k: v for k, v in result.answers.items() if k in present}


def plan_compaction(
    messages: Sequence[Message],
    usage: ContextUsage,
    asker: JevAsker,
    memory: CompactionMemory = CompactionMemory(),
    config: CompactionConfig = CompactionConfig(),
    level: TriggerLevel | None = None,
) -> PolicyOutcome:
    """Decides whether to compact now and whether the pruned transcript is worth applying.

    `level` forces the trigger (a compaction already under way); absent, the thresholds decide.
    soft/idle: apply when the result lands at or below target, frees min_freed_tokens, or the
    cache is cold anyway; otherwise defer and keep Jev's answers for the next round.
    manual: as soft, but the fallback is the summary the person asked for, not a deferral.
    hard: apply only when the result lands below soft; otherwise fall back to the summary.
    """
    if level is None:
        level = trigger_level(usage, memory, config)
    before = usage.percent
    if level is None:
        return PolicyOutcome("skip", None, None, 0, before, before, memory, "")
    must_shrink = level in ("hard", "manual")

    try:
        result = compact(messages, asker, config, memory.answers)
    except JevCompactionError as err:
        if must_shrink:
            return PolicyOutcome(
                "summarize", level, None, 0, before, before, CompactionMemory(),
                f"jev-compacter: Jev failed ({err}); falling back to built-in summary",
            )
        return PolicyOutcome(
            "defer", level, None, 0, before, before,
            CompactionMemory(usage.used_tokens, memory.answers),
            f"jev-compacter: Jev failed ({err}); deferred",
        )

    freed = max(
        0, sum(message_tokens(m) for m in messages) - sum(message_tokens(m) for m in result.messages)
    )
    after_tokens = max(0, usage.used_tokens - freed)
    after = 100 * after_tokens / usage.window_tokens
    cache_cold = usage.idle_seconds >= config.cache_idle_seconds

    if level == "hard":
        apply = after < config.soft_percent
    else:
        apply = freed > 0 and (
            after <= config.target_percent or freed >= config.min_freed_tokens or cache_cold
        )

    verdict = _verdict(result)
    action: PolicyAction
    if apply:
        action = "apply"
        next_memory = CompactionMemory(after_tokens, _surviving(result))
        message = f"jev-compacter: {verdict}; freed {_k(freed)} ({before:.0f}% → {after:.0f}%)"
    elif must_shrink:
        # The summary replaces the transcript, so nothing remembered still applies.
        action = "summarize"
        next_memory = CompactionMemory()
        message = (
            f"jev-compacter: {verdict}, freeing {_k(freed)}; not enough, "
            "falling back to built-in summary"
        )
        after = before
    else:
        action = "defer"
        next_memory = CompactionMemory(usage.used_tokens, result.answers)
        message = f"jev-compacter: {verdict}, freeing {_k(freed)}; not applied, deferred"
        after = before

    return PolicyOutcome(action, level, result, freed, before, after, next_memory, message)
