from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core import logs
from .hosts import codex as codex_host
from .tools.jev_router import context, journal, rules
from .tools.jev_router.catalog import CODEX_ALIASES, ModelInfo, load_catalog, save_catalog

MARKETPLACE = "Oqura-ai/optim-jev"
PLUGIN = "optim-jev@optim-jev"
_ASCII_CONSOLE = str.maketrans({"→": "->", "·": "|", "⬆": "up "})


class CliError(Exception):
    pass


def _console_text(text: str, stream: Any) -> str:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return text
    try:
        text.encode(encoding)
        return text
    except (LookupError, UnicodeEncodeError):
        safe = text.translate(_ASCII_CONSOLE)
        return safe.encode(encoding, errors="replace").decode(encoding)


def project_dir(value: str | os.PathLike[str] = ".") -> Path:
    start = Path(value).resolve()
    if not start.is_dir():
        start = start.parent
    return next((path for path in (start, *start.parents) if (path / ".git").exists()), start)


def _config_path(project: Path) -> Path:
    return project / ".optim-jev" / "config.json"


def _read_config(project: Path, *, strict: bool = False) -> dict[str, Any]:
    path = _config_path(project)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        if strict:
            raise CliError(f"{path} is not valid JSON: {error}") from error
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise CliError(f"{path} must contain a JSON object")
        return {}
    return raw


def _write_config(project: Path, **updates: Any) -> None:
    raw = _read_config(project, strict=True)
    codex = raw.get("codex")
    codex = dict(codex) if isinstance(codex, dict) else {}
    codex.update(updates)
    raw["codex"] = codex
    rules.write_atomic(_config_path(project), json.dumps(raw, indent=2, ensure_ascii=False) + "\n")


def _catalog_problems(project: Path) -> list[str]:
    catalog = load_catalog(project, host="codex")
    aliases = [model.alias for model in catalog]
    ids = [model.id for model in catalog]
    problems = []
    if set(aliases) != set(CODEX_ALIASES) or len(aliases) != len(CODEX_ALIASES):
        problems.append("model aliases must be exactly fast, balanced, and strong")
    if any(not model.id for model in catalog):
        problems.append("every model mapping needs a non-empty Codex model ID")
    if len(ids) != len(set(ids)):
        problems.append("Codex model IDs must be unique")
    if any(not model.available for model in catalog):
        problems.append("every configured Codex model must be available")
    problems.extend(rules.validate(project, CODEX_ALIASES, host="codex"))
    return problems


def _require_key() -> None:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise CliError("TYPESAFE_API_KEY is not set")


def _codex_executable() -> str:
    executable = shutil.which("codex.cmd" if os.name == "nt" else "codex") or shutil.which("codex")
    if not executable:
        raise CliError("codex is not on PATH")
    return executable


def _codex_models() -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            [_codex_executable(), "debug", "models"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CliError(f"could not run codex debug models: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise CliError(f"codex debug models failed: {detail[-1] if detail else result.returncode}")
    try:
        raw = json.loads(result.stdout)
    except ValueError as error:
        raise CliError("codex debug models did not return JSON") from error
    models = []
    for item in raw.get("models", ()) if isinstance(raw, dict) else ():
        if (
            not isinstance(item, dict)
            or not item.get("slug")
            or item.get("supported_in_api") is False
            or item.get("visibility") not in (None, "list")
        ):
            continue
        models.append(
            {
                "slug": str(item["slug"]),
                "name": str(item.get("display_name") or item["slug"]),
                "description": str(item.get("description") or ""),
            }
        )
    if not models:
        raise CliError("Codex reported no available models")
    return models


def _run_codex(*args: str, allow_missing: bool = False) -> str:
    try:
        result = subprocess.run(
            [_codex_executable(), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            shell=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CliError(f"could not run codex {' '.join(args)}: {error}") from error
    detail = (result.stderr or result.stdout).strip()
    if result.returncode and not (allow_missing and any(word in detail.lower() for word in ("not found", "not installed"))):
        raise CliError(detail or f"codex {' '.join(args)} failed with exit code {result.returncode}")
    return detail


def install(*, marketplace: str, ref: str | None) -> str:
    command = ["plugin", "marketplace", "add", marketplace]
    if ref:
        command += ["--ref", ref]
    _run_codex(*command)
    _run_codex("plugin", "add", PLUGIN)
    return "Codex plugin installed; restart Codex, then run optim-jev codex setup in your project"


def uninstall() -> str:
    _run_codex("plugin", "remove", PLUGIN, allow_missing=True)
    _run_codex("plugin", "marketplace", "remove", "optim-jev", allow_missing=True)
    return "Codex plugin and marketplace removed; uninstall Python separately with: py -3 -m pip uninstall optim-jev"


def _choose(label: str, models: list[dict[str, str]]) -> str:
    while True:
        value = input(f"{label} model (number or slug): ").strip()
        if value.isdigit() and 1 <= int(value) <= len(models):
            return models[int(value) - 1]["slug"]
        if any(model["slug"] == value for model in models):
            return value
        print("Choose one model from the list above.", file=sys.stderr)


def setup(project: Path, *, fast: str | None, balanced: str | None, strong: str | None, yes: bool) -> str:
    _require_key()
    _read_config(project, strict=True)
    models = _codex_models()
    available = {model["slug"] for model in models}
    supplied = (fast, balanced, strong)
    if any(supplied) and not all(supplied):
        raise CliError("--fast, --balanced, and --strong must be provided together")
    if not all(supplied):
        print("Available Codex models:")
        for index, model in enumerate(models, 1):
            detail = f" — {model['description']}" if model["description"] else ""
            print(f"  {index}. {model['slug']} ({model['name']}){detail}")
        fast = _choose("Fast", models)
        balanced = _choose("Balanced", models)
        strong = _choose("Strong", models)
    selected = (str(fast), str(balanced), str(strong))
    unknown = [model for model in selected if model not in available]
    if unknown:
        raise CliError("model(s) are not available: " + ", ".join(unknown))
    if len(set(selected)) != 3:
        raise CliError("fast, balanced, and strong must use three different model IDs")
    mapping = (
        ModelInfo("strong", 3, 5, "hard debugging, architecture, subtle invariants", selected[2]),
        ModelInfo("balanced", 2, 3, "feature work and refactors in known patterns", selected[1]),
        ModelInfo("fast", 1, 1, "mechanical edits, tests, docs, and renames", selected[0]),
    )
    problems = rules.validate(project, CODEX_ALIASES, host="codex")
    if problems:
        raise CliError("rules are invalid:\n- " + "\n- ".join(problems))
    print("Proposed mapping:")
    print(f"  fast      -> {selected[0]}")
    print(f"  balanced  -> {selected[1]}")
    print(f"  strong    -> {selected[2]}")
    if not yes and input("Write this mapping and enable routing? [y/N] ").strip().lower() not in ("y", "yes"):
        return "setup cancelled; no files changed"
    save_catalog(project, mapping, host="codex")
    if not (rules.router_dir(project) / rules.rules_filename("codex")).exists():
        rules.save(project, rules.Rules({}), host="codex")
    context_path = rules.router_dir(project) / context.context_filename("codex")
    if not context_path.exists():
        rules.write_atomic(
            context_path,
            context.markdown(context.Context(), setup_command="optim-jev codex setup"),
        )
    problems = _catalog_problems(project)
    if problems:
        raise CliError("saved catalog failed validation:\n- " + "\n- ".join(problems))
    _write_config(project, jev_router_mode="on", jev_router_cap="on", jev_router_max_input_tokens=4000)
    return "Codex routing configured and enabled"


def set_router(project: Path, on: bool) -> str:
    if on:
        _require_key()
        problems = _catalog_problems(project)
        if problems:
            raise CliError("cannot enable routing:\n- " + "\n- ".join(problems))
    _write_config(project, jev_router_mode="on" if on else "off")
    return f"Codex routing {'enabled' if on else 'disabled'}"


def set_skills(project: Path, on: bool) -> str:
    if on:
        _require_key()
    _write_config(project, jev_skills_mode="on" if on else "off")
    return f"Codex advisory skill shortlist {'enabled' if on else 'disabled'}"


def status(project: Path) -> dict[str, Any]:
    path = _config_path(project)
    malformed = None
    try:
        _read_config(project, strict=True)
    except CliError as error:
        malformed = str(error)
    options = codex_host.options(project)
    catalog = load_catalog(project, host="codex")
    router_mode = str(options.get("jev_router_mode") or "off").lower()
    catalog_path = project / ".optim-jev" / "jev_router" / "models.codex.json"
    return {
        "project": str(project),
        "router": router_mode,
        "skills": str(options.get("jev_skills_mode") or "off").lower(),
        "api_key_present": bool(os.environ.get("TYPESAFE_API_KEY")),
        "config": str(path) if path.exists() else None,
        "models": {model.alias: model.id for model in catalog},
        "rules": len(rules.load(project, CODEX_ALIASES, host="codex").paths),
        "problems": ([malformed] if malformed else [])
        + (_catalog_problems(project) if router_mode == "on" or catalog_path.exists() else []),
    }


def format_status(data: dict[str, Any]) -> str:
    lines = [
        f"Project: {data['project']}",
        f"Router: {data['router']}",
        f"Advisory skills: {data['skills']}",
        f"TYPESAFE_API_KEY: {'present' if data['api_key_present'] else 'missing'}",
        f"Path rules: {data['rules']}",
    ]
    models = data["models"]
    lines.append(
        "Models: "
        + (
            ", ".join(f"{alias}={models.get(alias) or 'missing'}" for alias in CODEX_ALIASES)
            if models
            else "not configured"
        )
    )
    lines.extend(f"Problem: {problem}" for problem in data["problems"] if problem)
    return "\n".join(lines)


def why(project: Path, session_id: str | None) -> str:
    if not session_id:
        folder = project / ".optim-jev" / "logs" / codex_host.TOOL
        candidates = list(folder.glob("*.jsonl")) if folder.is_dir() else []
        if not candidates:
            return "jev-router: no routed sessions logged yet"
        host_records = logs.read(
            max(candidates, key=lambda path: path.stat().st_mtime_ns),
            locked=True,
        )
        session_id = str(host_records[-1].get("session_id") or "") if host_records else ""
    return journal.why(journal.read(project, session_id, host="codex"), session_id)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="optim-jev")
    root.add_argument("--project", default=".", help="project directory (default: current repository)")
    hosts = root.add_subparsers(dest="host", required=True)
    codex = hosts.add_parser("codex", help="configure the Codex integration")
    actions = codex.add_subparsers(dest="action", required=True)
    install_parser = actions.add_parser("install", help="install the Codex plugin from a marketplace")
    install_parser.add_argument("--marketplace", default=MARKETPLACE)
    install_parser.add_argument("--ref", help="optional Git tag or branch to pin")
    actions.add_parser("uninstall", help="remove the Codex plugin and marketplace")
    setup_parser = actions.add_parser("setup", help="map available Codex models and enable routing")
    setup_parser.add_argument("--fast")
    setup_parser.add_argument("--balanced")
    setup_parser.add_argument("--strong")
    setup_parser.add_argument("--yes", action="store_true")
    help_text = {
        "on": "validate configuration and enable Codex routing",
        "off": "disable Codex routing",
        "skills-on": "enable the experimental advisory skill shortlist",
        "skills-off": "disable the experimental advisory skill shortlist",
    }
    for action, help_message in help_text.items():
        actions.add_parser(action, help=help_message)
    status_parser = actions.add_parser("status", help="show read-only Codex diagnostics")
    status_parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    why_parser = actions.add_parser("why", help="explain recent subagent routing decisions")
    why_parser.add_argument("--session")
    return root


def run(args: argparse.Namespace) -> str | dict[str, Any]:
    project = project_dir(args.project)
    if args.action == "install":
        return install(marketplace=args.marketplace, ref=args.ref)
    if args.action == "uninstall":
        return uninstall()
    if args.action == "setup":
        return setup(
            project,
            fast=args.fast,
            balanced=args.balanced,
            strong=args.strong,
            yes=args.yes,
        )
    if args.action == "on":
        return set_router(project, True)
    if args.action == "off":
        return set_router(project, False)
    if args.action == "skills-on":
        return set_skills(project, True)
    if args.action == "skills-off":
        return set_skills(project, False)
    if args.action == "status":
        data = status(project)
        return data if args.json else format_status(data)
    if args.action == "why":
        return why(project, args.session)
    raise CliError(f"unknown action: {args.action}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        answer = run(args)
    except CliError as error:
        print(_console_text(f"optim-jev: {error}", sys.stderr), file=sys.stderr)
        return 2
    rendered = json.dumps(answer) if isinstance(answer, dict) else answer
    print(_console_text(rendered, sys.stdout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
