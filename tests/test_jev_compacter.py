"""python -m unittest discover -s tests  (with PYTHONPATH=src)"""

from __future__ import annotations

import unittest

from optim_jev.tools.jev_compacter import stats
from optim_jev.tools.jev_compacter.config import CompactionConfig
from optim_jev.tools.jev_compacter.policy import plan_compaction, trigger_level
from optim_jev.tools.jev_compacter.tool import _usage
from optim_jev.tools.jev_compacter.types import CompactionMemory, ContextUsage, Message, ToolResult, ToolUse

CONFIG = CompactionConfig(preserve_recent_messages=0)
WINDOW = 200_000


class FakeJev:
    """Answers every keep question with `keep`; never contacts the API."""

    def __init__(self, keep: float) -> None:
        self.keep = keep

    def ask(self, state, questions):
        return {"answers": {name: {"noul": self.keep} for name in questions}}


def transcript() -> list[Message]:
    return [
        Message("user", "fix the parser"),
        Message("assistant", "", (ToolUse("t1", "Read", {"file_path": "parser.py"}),)),
        Message("user", "", (), (ToolResult("t1", "x = 1\n" * 2000),)),
        Message("assistant", "Fixed."),
    ]


def usage(percent: float, cold: bool = False) -> ContextUsage:
    return ContextUsage(int(WINDOW * percent / 100), WINDOW, idle_seconds=4000 if cold else 0, cache_cold=cold)


class ColdCache(unittest.TestCase):
    def test_idle_fires_only_when_the_cache_is_cold_and_above_target(self):
        memory = CompactionMemory()
        self.assertEqual(trigger_level(usage(50, cold=True), memory, CONFIG), "idle")
        self.assertIsNone(trigger_level(usage(50), memory, CONFIG))
        self.assertIsNone(trigger_level(usage(30, cold=True), memory, CONFIG))
        warm_but_idle = ContextUsage(100_000, WINDOW, idle_seconds=4000)
        self.assertIsNone(trigger_level(warm_but_idle, memory, CONFIG))  # idle time alone is not cold

    def test_a_cold_cache_applies_a_prune_too_small_to_apply_warm(self):
        cold = plan_compaction(transcript(), usage(50, cold=True), FakeJev(0.0), config=CONFIG, level="idle")
        warm = plan_compaction(transcript(), usage(50), FakeJev(0.0), config=CONFIG, level="idle")
        self.assertEqual(cold.action, "apply")
        self.assertLess(cold.freed_tokens, CONFIG.min_freed_tokens)
        self.assertEqual(warm.action, "defer")

    def test_idle_never_falls_back_to_the_summary(self):
        outcome = plan_compaction(transcript(), usage(50, cold=True), FakeJev(1.0), config=CONFIG, level="idle")
        self.assertEqual(outcome.action, "defer")

    def test_hard_does_not_apply_a_prune_that_frees_nothing(self):
        outcome = plan_compaction(transcript(), usage(20), FakeJev(1.0), config=CONFIG, level="hard")
        self.assertEqual(outcome.freed_tokens, 0)
        self.assertEqual(outcome.action, "summarize")

    def test_bridge_reads_cache_cold_strictly(self):
        self.assertTrue(_usage({"used_tokens": 1, "window_tokens": 2, "cache_cold": True}).cache_cold)
        self.assertFalse(_usage({"used_tokens": 1, "window_tokens": 2, "cache_cold": "yes"}).cache_cold)
        self.assertFalse(_usage({"used_tokens": 1, "window_tokens": 2}).cache_cold)


class Stats(unittest.TestCase):
    def test_applied_prune_is_compared_with_a_summary(self):
        compactions = [
            {"ts": 10, "kind": "compaction", "action": "apply", "used_tokens": 100_000, "freed_tokens_est": 60_000,
             "jev": {"requests": 1, "input_tokens": 5_000, "cost_usd": 0.0002}},
            {"ts": 20, "kind": "compaction", "action": "summarize", "used_tokens": 90_000,
             "jev": {"requests": 1, "input_tokens": 4_000, "cost_usd": 0.0001}},
        ]
        claude = [
            {"ts": 5, "kind": "turn", "agent_id": None, "model": "claude-sonnet-5-5"},
            {"ts": 21, "kind": "summary", "agent_id": None, "model": "claude-sonnet-5-5",
             "tokens_before": 90_000, "tokens_after": 9_000, "output_tokens": 4_500, "cache_read_input_tokens": 90_000},
        ]
        text = stats.report(compactions, claude)
        rows = {line.split("│")[1].strip(): line for line in text.splitlines() if line.startswith("│")}
        self.assertIn("2", rows["Compactions"])
        self.assertIn("$0.0001", rows["Jev cost on fallbacks"])
        self.assertIn("5.0%", rows["output, % of context"])
        self.assertIn("measured", rows["Jev pruning"])
        self.assertTrue(any(k.startswith("Net ") for k in rows))
        self.assertIn("measured from this session", text)

    def test_nothing_logged(self):
        self.assertIn("no compaction yet", stats.report([], []))


if __name__ == "__main__":
    unittest.main()
