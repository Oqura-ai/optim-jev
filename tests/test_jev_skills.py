"""python -m unittest discover -s tests  (with PYTHONPATH=src)"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from optim_jev.tools.jev_compacter.types import JevCompactionError
from optim_jev.tools.jev_skills import index, tool
from optim_jev.tools.jev_skills.config import SkillsConfig
from optim_jev.tools.jev_skills.index import Skill
from optim_jev.tools.jev_skills.pick import NONE, shortlist


def write_skill(folder: Path, name: str, description: str) -> None:
    (folder / name).mkdir(parents=True, exist_ok=True)
    (folder / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: >\n  {description}\n---\nbody\n")


class FakeJev:
    """Answers each choice question from `scores` (unlisted options get 0); records what it saw."""

    def __init__(self, scores: dict[str, float], fail: bool = False) -> None:
        self.scores = scores
        self.fail = fail
        self.seen: list[list[str]] = []

    def usage(self):
        return {"requests": len(self.seen), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    def ask(self, state, questions):
        if self.fail:
            raise JevCompactionError("down")
        options = list(questions["skill"]["criteria"])
        self.seen.append(options)
        return {"answers": {"skill": {"probabilities": {o: self.scores.get(o, 0.0) for o in options}}}}


class Index(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = Path(tempfile.mkdtemp())
        write_skill(self.root / ".claude/skills", "deploy", "Ship the app to staging")
        write_skill(self.home / "skills", "pptx", "Build slide decks")
        plugin = self.home / "plugins/cache/tools/1.0"
        write_skill(plugin / "skills", "lint", "Run the linters")
        (self.home / "plugins").mkdir(exist_ok=True)
        (self.home / "plugins/installed_plugins.json").write_text(
            json.dumps({"plugins": {"tools@market": [{"installPath": str(plugin)}]}})
        )
        self.env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_project_scope_reads_only_the_project(self):
        self.assertEqual([s.name for s in index.load(self.root, False)], ["deploy"])

    def test_global_scope_adds_user_and_plugin_skills_and_their_folders(self):
        roster = index.load(self.root, True)
        self.assertEqual([(s.name, s.source) for s in roster], [("deploy", "project"), ("pptx", "user"), ("tools:lint", "plugin:tools")])
        answer = tool.index_mode({"project_dir": str(self.root), "options": {}, "scope": "global"})
        self.assertEqual(len(answer["dirs"]), 2)  # user and plugin folders, never the project's

    def test_block_scalar_descriptions_are_joined(self):
        self.assertEqual(index.load(self.root, False)[0].description, "Ship the app to staging")


ROSTER = [Skill(f"s{i}", f"skill number {i}", "project", "/x") for i in range(45)]


class Pick(unittest.TestCase):
    def test_one_batch_is_final_and_none_sets_the_bar(self):
        jev = FakeJev({"s1": 0.5, "s2": 0.3, NONE: 0.35})
        result = shortlist("do the thing", [], ROSTER[:5], jev, SkillsConfig())
        self.assertEqual([s.name for s, _ in result.picks], ["s1"])  # s2 is under "none"
        self.assertEqual(result.calls, 1)

    def test_many_batches_get_a_second_round_over_the_leaders(self):
        jev = FakeJev({"s3": 0.6, "s25": 0.5, "s40": 0.2, NONE: 0.1})
        config = SkillsConfig(prefilter_above=100)
        result = shortlist("do the thing", [], ROSTER, jev, config)
        self.assertEqual(len(jev.seen), 4)  # 3 batches + the final round
        self.assertEqual(sorted(jev.seen[-1]), sorted(["s3", "s25", "s40", NONE]))
        self.assertEqual([s.name for s, _ in result.picks], ["s3", "s25"])

    def test_prefilter_keeps_the_closest_descriptions(self):
        jev = FakeJev({NONE: 1.0})
        shortlist("skill number 7", [], ROSTER, jev, SkillsConfig(prefilter_above=20))
        self.assertEqual(sum(len(o) - 1 for o in jev.seen[:1]), 20)

    def test_recent_user_inputs_reach_jev_oldest_first(self):
        states = []

        class Spy(FakeJev):
            def ask(self, state, questions):
                states.append(state)
                return super().ask(state, questions)

        shortlist("do the thing", ["first prompt", "second prompt"], ROSTER[:5], Spy({}), SkillsConfig())
        self.assertEqual(states[0]["recent_user_inputs"], ["first prompt", "second prompt"])
        self.assertNotIn("previous_assistant_message", states[0])

    def test_tight_budget_makes_smaller_batches(self):
        roomy, tight = FakeJev({"none": 1.0}), FakeJev({"none": 1.0})
        shortlist("do the thing", [], ROSTER, roomy, SkillsConfig())
        shortlist("do the thing", [], ROSTER, tight, SkillsConfig(max_input_tokens=220))
        self.assertGreater(len(tight.seen), len(roomy.seen))
        self.assertLess(max(len(options) for options in tight.seen), 21)

    def test_jev_failure_returns_no_picks_and_the_note_lists_names(self):
        root = Path(tempfile.mkdtemp())
        write_skill(root / ".claude/skills", "deploy", "Ship it")
        with mock.patch("optim_jev.tools.jev_skills.tool.JevClient", lambda **_: FakeJev({}, fail=True)):
            answer = tool.shortlist_mode({"project_dir": str(root), "options": {}, "prompt": "ship the release now"})
        self.assertEqual(answer["picks"], [])
        self.assertIn("Available skills: deploy", answer["context"])


if __name__ == "__main__":
    unittest.main()
