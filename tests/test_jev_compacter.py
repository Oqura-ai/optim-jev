from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from optim_jev.tools.jev_compacter import tool
from optim_jev.tools.jev_compacter.types import CompactionMemory, PolicyOutcome


class Bridge(unittest.TestCase):
    def test_compact_returns_the_estimated_tokens_freed(self):
        outcome = PolicyOutcome(
            action="defer",
            level="soft",
            result=None,
            freed_tokens=321,
            percent_before=60,
            percent_after=60,
            memory=CompactionMemory(),
            message="deferred",
        )
        request = {
            "session_id": "s",
            "project_dir": tempfile.mkdtemp(),
            "usage": {"used_tokens": 60_000, "window_tokens": 100_000},
            "options": {},
            "level": "soft",
            "messages": [],
        }
        with (
            mock.patch.object(tool, "locate_transcript", return_value=None),
            mock.patch.object(tool, "plan_compaction", return_value=outcome),
        ):
            answer = tool.compact(request)
        self.assertEqual(answer["freedTokensEst"], 321)


if __name__ == "__main__":
    unittest.main()
