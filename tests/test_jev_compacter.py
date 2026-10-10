"""python -m unittest discover -s tests  (with PYTHONPATH=src)"""

from __future__ import annotations

import unittest

from optim_jev.tools.jev_compacter import stats


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
