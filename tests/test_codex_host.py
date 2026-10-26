from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from optim_jev.core import logs
from optim_jev.hosts import codex
from optim_jev.tools.jev_router import rules as rules_mod
from optim_jev.tools.jev_router import tool as router
from optim_jev.tools.jev_router.catalog import ModelInfo, save_catalog


class FakeJev:
    def __init__(self, model: str = "fast", fail: bool = False) -> None:
        self.model = model
        self.fail = fail
        self.calls = 0
        self.states = []

    def ask(self, state, questions):
        self.calls += 1
        self.states.append(state)
        if self.fail:
            from optim_jev.tools.jev_compacter.types import JevCompactionError

            raise JevCompactionError("down")
        answers = {}
        for name, question in questions.items():
            choice = self.model if name in ("model", "skill") else "low"
            answers[name] = {
                "probabilities": {option: float(option == choice) for option in question["criteria"]}
            }
        return {"answers": answers}

    def usage(self):
        return {"requests": self.calls, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def configured_project() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / ".git").mkdir()
    (root / "src/core").mkdir(parents=True)
    (root / "src/core/db.py").write_text("x = 1\n")
    (root / "README.md").write_text("# Test\n")
    (root / ".optim-jev").mkdir()
    (root / ".optim-jev/config.json").write_text(json.dumps({"jev_router_mode": "on"}))
    save_catalog(
        root,
        (
            ModelInfo("strong", 3, 5, "hard work", "gpt-large"),
            ModelInfo("balanced", 2, 3, "normal work", "gpt-medium"),
            ModelInfo("fast", 1, 1, "small work", "gpt-small"),
        ),
        host="codex",
    )
    rules_mod.save(
        root,
        rules_mod.Rules(
            {"src/core/": rules_mod.Rule("src/core/", ("strong",), ("strong",), "subtle invariants")}
        ),
        host="codex",
    )
    return root


def write_skill(folder: Path, name: str, description: str) -> None:
    path = folder / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nUse this skill.\n"
    )


class Observe(unittest.TestCase):
    def test_event_metadata_is_logged_at_the_repository_root(self):
        root = configured_project()
        cwd = root / "packages/app"
        cwd.mkdir(parents=True)
        payload = {
            "session_id": "s/1",
            "turn_id": "t1",
            "agent_id": "a1",
            "cwd": str(cwd),
            "hook_event_name": "PreToolUse",
            "model": "gpt-codex",
            "tool_name": "Bash",
            "tool_use_id": "call-1",
            "tool_input": {"command": "echo secret"},
        }
        self.assertEqual(codex.dispatch(payload), {})
        records = logs.read(logs.session_file(root, "codex", "s/1"))
        self.assertEqual(
            {key: records[0][key] for key in ("event", "turn_id", "agent_id", "tool_name")},
            {"event": "PreToolUse", "turn_id": "t1", "agent_id": "a1", "tool_name": "Bash"},
        )
        self.assertNotIn("tool_input", records[0])

    def test_malformed_input_fails_open(self):
        script = Path(codex.__file__)
        result = subprocess.run(
            [sys.executable, str(script)],
            input="{not json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "{}", ""))

    def test_cross_process_jsonl_appends_remain_complete(self):
        path = Path(tempfile.mkdtemp()) / "events.jsonl"
        source = Path(__file__).resolve().parents[1] / "src"
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from optim_jev.core.logs import append\n"
            "for value in range(25): "
            "append(Path(sys.argv[1]), {'worker': int(sys.argv[2]), 'value': value}, locked=True)\n"
        )
        env = {**os.environ, "PYTHONPATH": str(source)}
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(path), str(worker)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for worker in range(4)
        ]
        for process in processes:
            _, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
        records = logs.read(path, locked=True)
        self.assertEqual(len(records), 100)
        self.assertEqual({record["worker"] for record in records}, set(range(4)))

    def test_lock_sidecars_are_codex_only(self):
        folder = Path(tempfile.mkdtemp())
        claude, codex_log = folder / "claude.jsonl", folder / "codex.jsonl"
        logs.append(claude, {"value": 1})
        logs.append(codex_log, {"value": 1}, locked=True)
        self.assertFalse(claude.with_name("claude.jsonl.lock").exists())
        self.assertTrue(codex_log.with_name("codex.jsonl.lock").exists())


class Router(unittest.TestCase):
    def setUp(self):
        self.root = configured_project()

    def event(self, event: str, **values):
        return {
            "session_id": "s1",
            "turn_id": "t1",
            "cwd": str(self.root),
            "hook_event_name": event,
            "model": "gpt-large",
            "permission_mode": "default",
            **values,
        }

    def spawn(self, message: str, call_id: str = "call-1", tool: str = "spawn_agent", **tool_input):
        return self.event(
            "PreToolUse", tool_name=tool, tool_use_id=call_id, tool_input={"message": message, **tool_input}
        )

    def patch(self, path: str, call_id: str = "call-1", **values):
        command = f"*** Begin Patch\n*** Update File: {path}\n@@\n-x = 1\n+x = 2\n*** End Patch\n"
        return {**self.event("PreToolUse", tool_name="apply_patch", tool_use_id=call_id, tool_input={"command": command}), **values}

    def routed(self, payload, jev=None):
        with mock.patch.object(router, "_jev", return_value=jev or FakeJev("fast")):
            return codex.dispatch(payload)["hookSpecificOutput"]["updatedInput"]

    def test_session_start_injects_codex_routing_instructions(self):
        answer = codex.dispatch(self.event("SessionStart", source="startup"))
        output = answer["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "SessionStart")
        self.assertIn("spawn_agent tool", output["additionalContext"])
        self.assertNotIn("Agent tool", output["additionalContext"])
        self.assertIn("rules.codex.json", output["additionalContext"])
        self.assertIn("fast, balanced, strong", output["additionalContext"])
        self.assertNotIn("rules.json:", output["additionalContext"])

    def test_windows_utf8_boms_are_accepted_in_local_json(self):
        for path in (
            self.root / ".optim-jev/config.json",
            self.root / ".optim-jev/jev_router/models.codex.json",
            self.root / ".optim-jev/jev_router/rules.codex.json",
        ):
            path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")
        answer = codex.dispatch(self.event("SessionStart", source="startup"))
        self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_spawn_rewrite_preserves_unknown_fields_and_disables_forked_history(self):
        for tool in ("spawn_agent", "collaborationspawn_agent"):
            with self.subTest(tool):
                updated = self.routed(
                    self.spawn("Update README.md", tool=tool, task_name="docs", fork_turns="all", future_field={"keep": True})
                )
                self.assertEqual((updated["model"], updated["reasoning_effort"]), ("gpt-small", "low"))
                self.assertEqual(updated["fork_turns"], "none")
                self.assertEqual(updated["future_field"], {"keep": True})

    def test_encrypted_collaboration_message_is_preserved_and_not_sent_to_jev(self):
        codex.dispatch(self.event("UserPromptSubmit", prompt="Ask a subagent to review the installation documentation"))
        encrypted = "gAAAAABopaque-codex-message"
        jev = FakeJev("fast")
        updated = self.routed(
            self.spawn(encrypted, tool="collaborationspawn_agent", task_name="installation_doc_review", fork_turns="all"), jev
        )
        self.assertEqual(updated["message"], encrypted)
        self.assertEqual(updated["fork_turns"], "none")
        self.assertNotIn(encrypted, str(jev.states))
        self.assertIn("installation_doc_review", str(jev.states))

    def test_recent_root_prompts_reach_routing_even_with_skills_disabled(self):
        self.assertEqual(codex.dispatch(self.event("UserPromptSubmit", prompt="Please update the documentation examples")), {})
        jev = FakeJev("fast")
        self.routed(self.spawn("Update README.md"), jev)
        self.assertIn("Please update the documentation examples", str(jev.states))

    def test_jev_failure_uses_a_deterministic_available_fallback(self):
        updated = self.routed(self.spawn("Update README.md", fork_context=True), FakeJev(fail=True))
        self.assertEqual(updated["model"], "gpt-large")
        self.assertFalse(updated["fork_context"])

    def test_repeated_agent_write_failures_escalate_the_next_matching_task(self):
        first = self.spawn("Update README.md", "spawn-1")
        self.assertEqual(self.routed(first)["model"], "gpt-small")
        codex.dispatch(
            self.event(
                "PostToolUse",
                tool_name="spawn_agent",
                tool_use_id="spawn-1",
                tool_input=first["tool_input"],
                tool_response={"result": {"agent_id": "agent-1"}},
            )
        )
        failed_patch = "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch\n"
        for index in range(4):
            codex.dispatch(
                self.event(
                    "PostToolUse",
                    agent_id="agent-1",
                    tool_name="apply_patch",
                    tool_use_id=f"edit-{index}",
                    tool_input={"command": failed_patch},
                    tool_response={"is_error": True, "message": "failed"},
                )
            )
        updated = self.routed(self.spawn("Update README.md again", "spawn-2"))
        self.assertEqual((updated["model"], updated["reasoning_effort"]), ("gpt-medium", "low"))
        records = logs.read(logs.session_file(self.root, "codex", "s1"))
        escalations = [record for record in records if record.get("kind") == "escalation"]
        self.assertEqual(
            [(record["from"], record["to"], record["files"]) for record in escalations],
            [("fast", "balanced", ["README.md"])],
        )

    def test_codex_activity_report_does_not_claim_model_cost_is_measured(self):
        self.routed(self.spawn("Update README.md"))
        text = router.stats_mode({"project_dir": str(self.root), "host": "codex", "session_id": "s1", "options": {}})["text"]
        self.assertIn("Routed subagents", text)
        self.assertNotIn("Subagents on routed models", text)
        self.assertNotIn("Same work on", text)
        self.assertNotIn("Decided by Claude", text)

    def test_root_writes_are_denied_but_shared_rules_remain_editable(self):
        def decision(payload):
            return codex.dispatch(payload).get("hookSpecificOutput", {}).get("permissionDecision")

        self.assertEqual(decision(self.patch("src/core/db.py")), "deny")
        self.assertIsNone(decision(self.patch(".optim-jev/jev_router/rules.codex.json", "call-2")))
        config = codex.dispatch(self.patch(".optim-jev/config.json", "call-3"))["hookSpecificOutput"]
        self.assertEqual(config["permissionDecision"], "deny")
        self.assertIn("optim-jev CLI", config["permissionDecisionReason"])
        self.assertEqual(decision(self.patch(".optim-jev/config.json", "call-4", agent_id="agent-1")), "deny")
        (self.root / ".optim-jev/config.json").write_text(json.dumps({"jev_router_mode": "off"}))
        self.assertEqual(decision(self.patch(".optim-jev/config.json", "call-5")), "deny")
        self.assertIsNone(decision(self.patch("src/core/db.py", "call-6")))

    def test_logging_failure_cannot_change_a_decision(self):
        with mock.patch.object(codex, "audit", side_effect=OSError("disk full")):
            denied = codex.dispatch(self.patch("src/core/db.py"))
            self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(self.routed(self.spawn("Update README.md", "call-2"))["model"], "gpt-small")

    def test_subagent_permissions_use_its_actual_model(self):
        event = self.patch("src/core/db.py", agent_id="a1")
        denied = codex.dispatch({**event, "model": "gpt-small"})
        self.assertIn("fast may not write", denied["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(codex.dispatch({**event, "model": "gpt-large"}), {})

    def test_write_targets_are_resolved_from_nested_session_cwd_and_cannot_escape(self):
        nested = self.root / "packages/app"
        nested.mkdir(parents=True)
        relative, outside = codex.target_relative("report.txt", self.root, nested)
        self.assertEqual((relative, outside), ("packages/app/report.txt", False))
        escaped, outside = codex.target_relative("../../../outside.txt", self.root, nested)
        self.assertTrue(outside)
        self.assertTrue(escaped.endswith("outside.txt"))

    def test_patch_and_shell_target_extractors_cover_moves_writes_and_reads(self):
        patch = (
            "*** Begin Patch\n"
            "*** Update File: src/old.py\n"
            "*** Move to: src/new.py\n"
            "@@\n-x\n+y\n"
            "*** Delete File: src/gone.py\n"
            "*** End Patch\n"
        )
        self.assertEqual(
            codex.patch_targets(patch),
            [("src/old.py", "delete"), ("src/new.py", "write"), ("src/gone.py", "delete")],
        )
        self.assertEqual(codex.shell_targets("cat src/a.py | rg x"), [])
        self.assertEqual(
            codex.shell_targets('cp src/a.py "src/b.py"; echo ok > reports/out.txt; rm src/old.py'),
            [("reports/out.txt", "write"), ("src/b.py", "write"), ("src/old.py", "delete")],
        )
        self.assertEqual(
            codex.shell_targets("New-Item -ItemType File -Path src/new.py"),
            [("src/new.py", "write")],
        )
        self.assertEqual(codex._agent_id('spawned agent_id: "agent-9"'), "agent-9")
        self.assertTrue(codex._failed({"exitCode": 2}))


class SkillsExperiment(unittest.TestCase):
    def setUp(self):
        self.root = configured_project()
        write_skill(self.root / ".agents/skills", "deploy", "Deploy the app to staging")

    def prompt(self, **values):
        return {
            "session_id": "s1",
            "turn_id": "t1",
            "cwd": str(self.root),
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-large",
            "permission_mode": "default",
            "prompt": "Deploy this application to staging",
            **values,
        }

    def enable(self):
        config = json.loads((self.root / ".optim-jev/config.json").read_text())
        config["jev_skills_mode"] = "on"
        (self.root / ".optim-jev/config.json").write_text(json.dumps(config))

    def test_disabled_by_default_does_not_call_jev_or_add_context(self):
        with mock.patch.object(codex.skills, "JevClient", side_effect=AssertionError("must stay off")):
            self.assertEqual(codex.dispatch(self.prompt()), {})

    def test_root_prompt_gets_an_advisory_shortlist_when_explicitly_enabled(self):
        self.enable()
        with mock.patch.object(codex.skills, "JevClient", return_value=FakeJev("deploy")):
            answer = codex.dispatch(self.prompt())
        context = answer["hookSpecificOutput"]["additionalContext"]
        self.assertIn("deploy", context)
        self.assertIn("use that skill's instructions", context)
        self.assertNotIn("Skill tool", context)

    def test_subagent_prompts_and_jev_failures_leave_native_selection_unchanged(self):
        self.enable()
        with mock.patch.object(codex.skills, "JevClient", return_value=FakeJev(fail=True)):
            self.assertEqual(codex.dispatch(self.prompt(agent_id="agent-1")), {})
            self.assertEqual(codex.dispatch(self.prompt()), {})

    def test_roots_cover_nested_repo_user_and_admin_locations(self):
        nested = self.root / "packages/app"
        nested.mkdir(parents=True)
        home = Path(tempfile.mkdtemp())
        payload = self.prompt(cwd=str(nested))
        with mock.patch.object(Path, "home", return_value=home):
            roots = codex.skill_roots(payload, self.root)
        paths = {root["path"] for root in roots}
        self.assertIn(str(nested / ".agents/skills"), paths)
        self.assertIn(str(self.root / ".agents/skills"), paths)
        self.assertIn(str(home / ".agents/skills"), paths)
        if os.name != "nt":
            self.assertIn("/etc/codex/skills", paths)


class Packaging(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_codex_manifest_is_separate_and_matches_claude_identity(self):
        plugin_root = self.root / "codex-plugin"
        codex_manifest = json.loads((plugin_root / ".codex-plugin/plugin.json").read_text())
        claude_manifest = json.loads((self.root / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(
            (codex_manifest["name"], codex_manifest["version"], codex_manifest["license"]),
            (claude_manifest["name"], claude_manifest["version"], claude_manifest["license"]),
        )
        self.assertEqual(codex_manifest["hooks"], "./hooks/codex-hooks.json")
        self.assertTrue((plugin_root / codex_manifest["hooks"]).is_file())
        self.assertNotIn("skills", codex_manifest)
        self.assertFalse((self.root / "plugin.json").exists())
        self.assertEqual(json.loads((self.root / "hooks/hooks.json").read_text()), {"modules": ["./optim-jev.ts"]})
        marketplace = json.loads((self.root / ".agents/plugins/marketplace.json").read_text())["plugins"][0]
        self.assertEqual((marketplace["name"], marketplace["source"]), ("optim-jev", {"source": "local", "path": "./codex-plugin"}))
        self.assertEqual(
            {
                path.relative_to(plugin_root).as_posix()
                for path in plugin_root.rglob("*")
                if path.is_file()
            },
            {
                ".codex-plugin/plugin.json",
                "hooks/codex-hooks.json",
                "hooks/run-codex-hook.py",
            },
        )

    def test_hooks_cover_only_events_that_implement_product_behavior(self):
        hooks = json.loads((self.root / "codex-plugin/hooks/codex-hooks.json").read_text())["hooks"]
        self.assertEqual(
            set(hooks),
            {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"},
        )
        handlers = [handler for groups in hooks.values() for group in groups for handler in group["hooks"]]
        self.assertTrue(all(handler.get("commandWindows") for handler in handlers))
        self.assertTrue(all(handler["command"].startswith("python3 -c ") for handler in handlers))
        self.assertTrue(all(handler["commandWindows"].startswith("py -3 -c ") for handler in handlers))
        self.assertIn("collaborationspawn_agent", hooks["PreToolUse"][0]["matcher"])

    def test_hook_runner_fails_open_when_the_python_package_is_unavailable(self):
        runner = self.root / "codex-plugin/hooks/run-codex-hook.py"
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                [sys.executable, "-S", str(runner)],
                input="{}",
                text=True,
                cwd=cwd,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "{}")

    def test_hook_launcher_runs_from_the_packaged_plugin_root(self):
        hooks = json.loads((self.root / "codex-plugin/hooks/codex-hooks.json").read_text())["hooks"]
        command = hooks["SessionStart"][0]["hooks"][0]["commandWindows" if os.name == "nt" else "command"]
        env = {**os.environ, "PLUGIN_ROOT": str(self.root / "codex-plugin")}
        with tempfile.TemporaryDirectory() as cwd:
            result = subprocess.run(
                command,
                input=json.dumps({"hook_event_name": "SessionStart", "cwd": cwd}),
                text=True,
                shell=True,
                cwd=cwd,
                env=env,
                capture_output=True,
                check=False,
            )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "{}", ""))


if __name__ == "__main__":
    unittest.main()
