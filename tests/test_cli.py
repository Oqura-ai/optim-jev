from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from optim_jev import cli
from optim_jev.core import logs
from optim_jev.tools.jev_router import journal


class CodexCli(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".git").mkdir()
        self.models = [
            {"slug": "gpt-fast", "name": "Fast", "description": ""},
            {"slug": "gpt-balanced", "name": "Balanced", "description": ""},
            {"slug": "gpt-strong", "name": "Strong", "description": ""},
        ]

    def invoke(self, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--project", str(self.root), "codex", *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def setup_codex(self, *extra: str, key: str | None = "secret") -> tuple[int, str, str]:
        env = {"TYPESAFE_API_KEY": key} if key else {}
        with (
            mock.patch.dict(os.environ, env, clear=key is None),
            mock.patch.object(cli, "_codex_models", return_value=self.models),
        ):
            return self.invoke(
                "setup", "--fast", "gpt-fast", "--balanced", "gpt-balanced", "--strong", "gpt-strong", *extra
            )

    def test_model_discovery_decodes_utf8_and_filters_hidden_models(self):
        result = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "models": [
                        {
                            "slug": "gpt-visible",
                            "display_name": "Visible",
                            "description": "Unicode → works",
                            "visibility": "list",
                            "supported_in_api": True,
                        },
                        {"slug": "gpt-hidden", "visibility": "hide"},
                    ]
                },
                ensure_ascii=False,
            ),
            stderr="",
        )
        with (
            mock.patch.object(cli.shutil, "which", return_value="codex.cmd"),
            mock.patch.object(cli.subprocess, "run", return_value=result) as run,
        ):
            models = cli._codex_models()
        self.assertEqual([model["slug"] for model in models], ["gpt-visible"])
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")

    def test_console_output_falls_back_to_ascii_on_windows_code_pages(self):
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        self.assertEqual(
            cli._console_text("task → haiku · low ⬆1", stream),
            "task -> haiku | low up 1",
        )

    def test_setup_writes_validated_catalog_then_enables_routing(self):
        code, output, errors = self.setup_codex("--yes")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("configured and enabled", output)
        config = json.loads((self.root / ".optim-jev/config.json").read_text())
        self.assertEqual(config["codex"]["jev_router_mode"], "on")
        catalog = json.loads((self.root / ".optim-jev/jev_router/models.codex.json").read_text())
        self.assertEqual(
            {model["alias"]: model["id"] for model in catalog},
            {"fast": "gpt-fast", "balanced": "gpt-balanced", "strong": "gpt-strong"},
        )
        self.assertTrue((self.root / ".optim-jev/jev_router/rules.codex.json").is_file())
        self.assertTrue((self.root / ".optim-jev/jev_router/RULES.codex.md").is_file())
        self.assertFalse((self.root / ".optim-jev/jev_router/rules.json").exists())

    def test_setup_without_a_key_or_when_cancelled_writes_nothing(self):
        code, _, errors = self.setup_codex("--yes", key=None)
        self.assertEqual(code, 2)
        self.assertIn("TYPESAFE_API_KEY", errors)
        with mock.patch("builtins.input", return_value="no"):
            code, output, errors = self.setup_codex()
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("no files changed", output)
        self.assertFalse((self.root / ".optim-jev").exists())

    def test_setup_refuses_invalid_existing_rules_before_writing_catalog_or_config(self):
        folder = self.root / ".optim-jev/jev_router"
        folder.mkdir(parents=True)
        (folder / "rules.codex.json").write_text('{"paths":{"src/":{"write":["unknown"]}}}')
        code, _, errors = self.setup_codex("--yes")
        self.assertEqual(code, 2)
        self.assertIn("unknown model", errors)
        self.assertFalse((folder / "models.codex.json").exists())
        self.assertFalse((self.root / ".optim-jev/config.json").exists())

    def test_setup_refuses_malformed_config_before_writing_catalog(self):
        folder = self.root / ".optim-jev"
        folder.mkdir()
        (folder / "config.json").write_text("{broken")
        code, _, errors = self.setup_codex("--yes")
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", errors)
        self.assertFalse((folder / "jev_router/models.codex.json").exists())

    def test_status_is_read_only_and_reports_missing_configuration(self):
        code, output, errors = self.invoke("status")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("Router: off", output)
        self.assertIn("Models: not configured", output)
        self.assertEqual(json.loads(self.invoke("status", "--json")[1])["router"], "off")
        self.assertFalse((self.root / ".optim-jev").exists())

    def test_off_preserves_non_codex_configuration(self):
        folder = self.root / ".optim-jev"
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps({"shared": 1, "codex": {"jev_skills_mode": "on"}}))
        code, _, errors = self.invoke("off")
        self.assertEqual((code, errors), (0, ""))
        config = json.loads((folder / "config.json").read_text())
        self.assertEqual(config["shared"], 1)
        self.assertEqual(
            config["codex"],
            {"jev_skills_mode": "on", "jev_router_mode": "off"},
        )

    def test_on_refuses_missing_model_catalog(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "secret"}):
            code, _, errors = self.invoke("on")
        self.assertEqual(code, 2)
        self.assertIn("model aliases", errors)
        self.assertFalse((self.root / ".optim-jev").exists())

    def test_why_uses_the_newest_session_unless_one_is_named(self):
        logs.append(
            logs.session_file(self.root, "codex", "session/1"),
            {"session_id": "session/1", "kind": "hook"},
        )
        journal.append(
            self.root,
            "session/1",
            {
                "kind": "spawn",
                "model": "fast",
                "description": "tests",
                "source": "jev",
                "allowed": ["fast"],
            },
            host="codex",
        )
        code, output, errors = self.invoke("why")
        self.assertEqual((code, errors), (0, ""))
        self.assertIn("tests → fast", output)

    def test_install_and_uninstall_run_native_codex_commands_in_order_without_a_shell(self):
        def run(*args: str) -> tuple[str, list[list[str]]]:
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            with (
                mock.patch.object(cli, "_codex_executable", return_value="codex.cmd"),
                mock.patch.object(cli.subprocess, "run", return_value=completed) as process,
            ):
                code, output, errors = self.invoke(*args)
            self.assertEqual((code, errors), (0, ""))
            self.assertTrue(all(call.kwargs["shell"] is False for call in process.call_args_list))
            return output, [call.args[0] for call in process.call_args_list]

        output, commands = run("install", "--ref", "v1.2.3")
        self.assertIn("restart Codex", output)
        self.assertEqual(commands, [
            ["codex.cmd", "plugin", "marketplace", "add", "Oqura-ai/optim-jev", "--ref", "v1.2.3"],
            ["codex.cmd", "plugin", "add", "optim-jev@optim-jev"],
        ])
        output, commands = run("uninstall")
        self.assertIn("pip uninstall", output)
        self.assertEqual(commands, [
            ["codex.cmd", "plugin", "remove", "optim-jev@optim-jev"],
            ["codex.cmd", "plugin", "marketplace", "remove", "optim-jev"],
        ])


if __name__ == "__main__":
    unittest.main()
