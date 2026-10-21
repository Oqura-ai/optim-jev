"""Codex command-hook adapter: one JSON event on stdin, one JSON result on stdout.

The adapter owns Codex wire formats only. Router decisions remain in `tools.jev_router`, and every
adapter failure is fail-open so optim-jev never makes Codex unusable.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from optim_jev.core import logs
from optim_jev.tools.jev_skills import tool as skills
from optim_jev.tools.jev_router import rules as rules_mod
from optim_jev.tools.jev_router import tool as router
from optim_jev.tools.jev_router.catalog import CODEX_ALIASES, ModelInfo, alias_of, load_catalog

TOOL = "codex"
CONTROL_FILES = {
    ".optim-jev/jev_router/rules.codex.json",
    ".optim-jev/jev_router/RULES.codex.md",
}
CLI_FILES = {
    ".optim-jev/config.json",
    ".optim-jev/jev_router/models.codex.json",
}
FIELDS = (
    "turn_id",
    "agent_id",
    "agent_type",
    "model",
    "permission_mode",
    "source",
    "trigger",
    "tool_name",
    "tool_use_id",
)
ENV_OPTIONS = {
    "OPTIM_JEV_ROUTER_CAP": "jev_router_cap",
    "OPTIM_JEV_ROUTER_ESCALATE_AFTER": "jev_router_escalate_after",
    "OPTIM_JEV_ROUTER_MAX_INPUT_TOKENS": "jev_router_max_input_tokens",
    "OPTIM_JEV_ROUTER_MODEL": "jev_router_model",
    "OPTIM_JEV_ROUTER_BASE_URL": "jev_router_base_url",
    "OPTIM_JEV_ROUTER_MODE": "jev_router_mode",
    "OPTIM_JEV_SKILLS_BASE_URL": "jev_skills_base_url",
    "OPTIM_JEV_SKILLS_MAX_INPUT_TOKENS": "jev_skills_max_input_tokens",
    "OPTIM_JEV_SKILLS_MAX_PICKS": "jev_skills_max_picks",
    "OPTIM_JEV_SKILLS_MIN_PERCENT": "jev_skills_min_percent",
    "OPTIM_JEV_SKILLS_MODE": "jev_skills_mode",
    "OPTIM_JEV_SKILLS_MODEL": "jev_skills_model",
}
_PATCH_HEADER = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)
_MOVE_HEADER = re.compile(r"^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)
_SEGMENT = re.compile(r"&&|\|\||[;|\n]")
_WORD = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_REDIRECT = re.compile(r"(?:^|\s)(?:\d*)>>?\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))")


def project_dir(cwd: object) -> Path:
    try:
        start = Path(os.fspath(cwd)).resolve()
    except (OSError, TypeError, ValueError):
        start = Path.cwd()
    if not start.is_dir():
        start = start.parent
    return next((path for path in (start, *start.parents) if (path / ".git").exists()), start)


def observe(payload: dict[str, Any]) -> None:
    event = payload.get("hook_event_name")
    if not isinstance(event, str) or not event:
        return
    session_id = str(payload.get("session_id") or "")
    record = {
        "session_id": session_id,
        "kind": "hook",
        "event": event,
        **{key: payload[key] for key in FIELDS if payload.get(key) is not None},
    }
    logs.append(
        logs.session_file(project_dir(payload.get("cwd")), TOOL, session_id),
        record,
        locked=True,
    )


def audit(payload: dict[str, Any], record: dict[str, Any]) -> None:
    session_id = str(payload.get("session_id") or "")
    logs.append(
        logs.session_file(project_dir(payload.get("cwd")), TOOL, session_id),
        {"session_id": session_id, **record},
        locked=True,
    )


def audit_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return logs.read(
            logs.session_file(
                project_dir(payload.get("cwd")),
                TOOL,
                str(payload.get("session_id") or ""),
            ),
            locked=True,
        )
    except Exception:
        return []


def escalation_state(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for record in audit_records(payload):
        if record.get("kind") != "escalation":
            continue
        for path in record.get("files") or ():
            if isinstance(path, str):
                previous = state.get(path, {})
                state[path] = {
                    "levels": int(previous.get("levels") or 0) + 1,
                    "effort": record.get("effort"),
                }
    return state


def options(project: Path) -> dict[str, Any]:
    try:
        raw = json.loads((project / ".optim-jev/config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    nested = raw.get("codex")
    if isinstance(nested, dict):
        raw = {**raw, **nested}
    result = {str(key): value for key, value in raw.items() if str(key).startswith("jev_")}
    for env, key in ENV_OPTIONS.items():
        if os.environ.get(env):
            result[key] = os.environ[env]
    return result


def request(payload: dict[str, Any], project: Path, **extra: Any) -> dict[str, Any]:
    return {
        "project_dir": str(project),
        "host": "codex",
        "options": options(project),
        "session_id": str(payload.get("session_id") or ""),
        "session_model": str(payload.get("model") or ""),
        **extra,
    }


def enabled(project: Path) -> bool:
    return str(options(project).get("jev_router_mode") or "off").lower() == "on"


def skills_enabled(project: Path) -> bool:
    return str(options(project).get("jev_skills_mode") or "off").lower() == "on"


def valid_catalog(catalog: tuple[ModelInfo, ...]) -> bool:
    aliases = [model.alias for model in catalog]
    ids = [model.id for model in catalog]
    return (
        len(aliases) == len(CODEX_ALIASES)
        and set(aliases) == set(CODEX_ALIASES)
        and all(ids)
        and len(ids) == len(set(ids))
        and all(model.available for model in catalog)
    )


def skill_roots(payload: dict[str, Any], project: Path) -> list[dict[str, str]]:
    cwd = Path(str(payload.get("cwd") or project)).resolve()
    try:
        cwd.relative_to(project)
    except ValueError:
        cwd = project
    roots = []
    current = cwd
    while True:
        roots.append({"source": "project", "prefix": "", "path": str(current / ".agents/skills")})
        if current == project:
            break
        current = current.parent
    roots.append({"source": "user", "prefix": "", "path": str(Path.home() / ".agents/skills")})
    if os.name != "nt":
        roots.append({"source": "admin", "prefix": "", "path": "/etc/codex/skills"})
    return roots


def prompt_submit(payload: dict[str, Any], project: Path) -> dict[str, Any]:
    if payload.get("agent_id"):
        return {}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return {}
    text = prompt.strip()
    recent = [
        str(record["prompt"])
        for record in audit_records(payload)
        if record.get("kind") == "prompt" and isinstance(record.get("prompt"), str)
    ][-3:]
    if enabled(project) or skills_enabled(project):
        try:
            audit(payload, {"kind": "prompt", "turn_id": payload.get("turn_id"), "prompt": text[:2000]})
        except Exception:
            pass
    if not skills_enabled(project):
        return {}
    if len(text) < 12 or text.startswith("/") or text.lower() in {
        "yes",
        "no",
        "ok",
        "okay",
        "continue",
        "go ahead",
    }:
        return {}
    skill_options = options(project)
    skill_options.setdefault("jev_skills_scope", "global")
    answer = skills.shortlist_mode(
        {
            "project_dir": str(project),
            "host": "codex",
            "options": skill_options,
            "session_id": str(payload.get("session_id") or ""),
            "prompt": text,
            "recent_inputs": recent,
            "skill_roots": skill_roots(payload, project),
        }
    )
    context = answer.get("context")
    if not isinstance(context, str) or not context:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def session_start(payload: dict[str, Any], project: Path) -> dict[str, Any]:
    if not enabled(project) or not valid_catalog(load_catalog(project, host="codex")):
        return {}
    answer = router.render_mode(request(payload, project))
    if not answer.get("tiers"):
        return {}
    section = str(answer.get("section") or "").replace("Agent tool", "spawn_agent tool")
    if not section:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": section,
        }
    }


def route_spawn(payload: dict[str, Any], project: Path) -> dict[str, Any]:
    raw = payload.get("tool_input")
    if not enabled(project) or not isinstance(raw, dict):
        return {}
    catalog = load_catalog(project, host="codex")
    if not valid_catalog(catalog):
        return {}
    prompt_key = "message" if isinstance(raw.get("message"), str) else "prompt"
    prompt = raw.get(prompt_key)
    if not isinstance(prompt, str) or not prompt.strip():
        return {}
    recent_inputs = [
        str(record["prompt"])
        for record in audit_records(payload)
        if record.get("kind") == "prompt" and isinstance(record.get("prompt"), str)
    ][-3:]
    description = next(
        (
            str(raw[key])
            for key in ("task_name", "agent_type", "description")
            if isinstance(raw.get(key), str) and raw[key]
        ),
        "subagent",
    )
    opaque_prompt = prompt.startswith("gAAAAA")
    routing_prompt = prompt
    if opaque_prompt:
        routing_prompt = "\n\n".join((*recent_inputs, f"Subagent task: {description}"))
    spawn_request = request(
        payload,
        project,
        description=description,
        prompt=routing_prompt,
        escalated=escalation_state(payload),
        recent_inputs=recent_inputs,
    )
    answer = router.spawn_mode(spawn_request)
    if answer.get("ask_claude"):
        answer = router.spawn_mode(
            {
                **spawn_request,
                "decided": {
                    "failed": "routing input exceeded the Codex hook budget; used deterministic fallback"
                },
            }
        )
    selected = next((model for model in catalog if model.alias == answer.get("model")), None)
    if selected is None or not selected.id or not selected.available:
        return {}
    updated = dict(raw)
    if not opaque_prompt:
        updated[prompt_key] = prompt + str(answer.get("appendix") or "")
    updated["model"] = selected.id
    if answer.get("effort"):
        updated["reasoning_effort"] = answer["effort"]
    if "fork_turns" in updated:
        updated["fork_turns"] = "none"
    if "fork_context" in updated:
        updated["fork_context"] = False
    try:
        audit(
            payload,
            {
                "kind": "route",
                "tool_use_id": str(payload.get("tool_use_id") or ""),
                "turn_id": payload.get("turn_id"),
                "model": answer.get("model"),
                "model_id": selected.id,
                "effort": answer.get("effort"),
                "files": answer.get("files") or [],
                "source": answer.get("source"),
            },
        )
    except Exception:
        pass
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated,
        }
    }


def patch_targets(command: str) -> list[tuple[str, str]]:
    matches = list(_PATCH_HEADER.finditer(command))
    targets: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        action, path = match.group(1).lower(), match.group(2).strip()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(command)
        move = _MOVE_HEADER.search(command, match.end(), body_end)
        if action == "delete":
            targets.append((path, "delete"))
        elif action == "update" and move:
            targets.extend(((path, "delete"), (move.group(1).strip(), "write")))
        else:
            targets.append((path, "write"))
    return targets


def _words(segment: str) -> list[str]:
    return [next(group for group in match.groups() if group is not None) for match in _WORD.finditer(segment)]


def shell_targets(command: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for match in _REDIRECT.finditer(command):
        targets.append((next(group for group in match.groups() if group is not None), "write"))
    for segment in _SEGMENT.split(command):
        argv = _words(segment.strip())
        if not argv:
            continue
        if argv[0].lower() == "sudo":
            argv = argv[1:]
        if len(argv) > 1 and argv[0].lower() == "git" and argv[1].lower() in ("rm", "mv"):
            argv = argv[1:]
        if not argv:
            continue
        name = argv[0].lower()
        raw_args = argv[1:]
        args = [arg for arg in raw_args if not arg.startswith("-")]
        if name in ("rm", "rmdir", "del", "erase", "unlink", "remove-item", "ri"):
            targets.extend((path, "delete") for path in args)
        elif name in ("mv", "move", "move-item") and len(args) >= 2:
            targets.extend(((path, "delete") for path in args[:-1]))
            targets.append((args[-1], "write"))
        elif name in ("cp", "copy", "copy-item", "ci", "install") and len(args) >= 2:
            targets.append((args[-1], "write"))
        elif name in ("touch", "mkdir", "tee"):
            targets.extend((path, "write") for path in args)
        elif name in ("new-item", "set-content", "add-content", "out-file"):
            path = next(
                (raw_args[i + 1] for i, arg in enumerate(raw_args[:-1]) if arg.lower() == "-path"),
                args[-1] if args else None,
            )
            if path:
                targets.append((path, "write"))
    return list(dict.fromkeys(targets))


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def record_denial(payload: dict[str, Any], project: Path, reason: str, path: str) -> dict[str, Any]:
    answer = deny(reason)
    try:
        audit(
            payload,
            {
                "kind": "denial",
                "turn_id": payload.get("turn_id"),
                "agent_id": payload.get("agent_id"),
                "path": path,
                "reason": reason,
            },
        )
        if enabled(project):
            router.outcome_mode(
                request(
                    payload,
                    project,
                    record={"turn_id": payload.get("turn_id"), "denials": 1, "escalations": []},
                )
            )
    except Exception:
        pass
    return answer


def target_relative(path: str, project: Path, cwd: object) -> tuple[str, bool]:
    root = project.absolute()
    try:
        root = project.resolve()
        base = Path(os.fspath(cwd)).resolve()
        base.relative_to(root)
    except (OSError, TypeError, ValueError):
        base = root
    try:
        raw = Path(path)
        if raw.drive and raw.drive.casefold() != root.drive.casefold():
            return path.replace("\\", "/"), True
        target = (raw if raw.is_absolute() else base / raw).resolve()
        return target.relative_to(root).as_posix(), False
    except (OSError, ValueError):
        return rules_mod.relative(path, project).rstrip("/"), True


def guard_write(payload: dict[str, Any], project: Path) -> dict[str, Any]:
    raw = payload.get("tool_input")
    if not isinstance(raw, dict) or not isinstance(raw.get("command"), str):
        return {}
    tool_name = str(payload.get("tool_name") or "")
    targets = patch_targets(raw["command"]) if tool_name == "apply_patch" else shell_targets(raw["command"])
    if not targets:
        return {}
    relative = [
        (*target_relative(path, project, payload.get("cwd")), kind)
        for path, kind in targets
    ]
    checked = [(path, kind) for path, _, kind in relative]
    cli_files = {path.casefold() for path in CLI_FILES}
    cli_only = next((path for path, _ in checked if path.casefold() in cli_files), None)
    if cli_only is not None:
        reason = f"optim-jev router: {cli_only} can only be changed with the optim-jev CLI"
        return record_denial(payload, project, reason, cli_only)
    if not enabled(project):
        return {}
    outside = next((path for path, is_outside, _ in relative if is_outside), None)
    if outside:
        reason = f"optim-jev router: refusing a write outside the project: {outside}"
        return record_denial(payload, project, reason, outside)
    if not payload.get("agent_id"):
        control = {path.casefold() for path in CONTROL_FILES}
        blocked = next((path for path, _ in checked if path.casefold() not in control), None)
        if blocked is None:
            return {}
        reason = f"optim-jev router: the root agent cannot write {blocked}; delegate the change with spawn_agent"
        return record_denial(payload, project, reason, blocked)
    catalog = load_catalog(project, host="codex")
    model = alias_of(str(payload.get("model") or ""), catalog, host="codex")
    if model is None:
        return {}
    known = tuple(reversed([item.alias for item in catalog]))
    rules = rules_mod.load(project, known, host="codex")
    for path, kind in checked:
        rule = rules_mod.resolve(rules, path)
        allowed = getattr(rule, kind) if rule is not None else known
        if model not in allowed:
            reason = f"optim-jev router: {model} may not {kind} {path}"
            return record_denial(payload, project, reason, path)
    return {}


def _agent_id(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("agent_id", "agentId"):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
        return next((found for child in value.values() if (found := _agent_id(child))), None)
    if isinstance(value, list):
        return next((found for child in value if (found := _agent_id(child))), None)
    if isinstance(value, str):
        match = re.search(r"\bagent[_ ]id\b[\"']?\s*[:=]\s*[\"']?([\w-]+)", value, re.IGNORECASE)
        return match.group(1) if match else None
    return None


def _failed(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("is_error") is True or value.get("isError") is True or value.get("success") is False:
            return True
        exit_code = value.get("exit_code", value.get("exitCode"))
        if isinstance(exit_code, int) and exit_code != 0:
            return True
        if str(value.get("status") or "").lower() in ("error", "failed", "failure"):
            return True
        return any(_failed(child) for child in value.values() if isinstance(child, (dict, list)))
    if isinstance(value, list):
        return any(_failed(child) for child in value)
    return False


def _route_for_agent(records: list[dict[str, Any]], agent_id: str) -> dict[str, Any] | None:
    link = next(
        (record for record in reversed(records) if record.get("kind") == "agent_link" and record.get("agent_id") == agent_id),
        None,
    )
    if link is None:
        return None
    return next(
        (
            record
            for record in reversed(records)
            if record.get("kind") == "route" and record.get("tool_use_id") == link.get("tool_use_id")
        ),
        None,
    )


def _escalate_after(project: Path) -> int:
    try:
        return max(1, int(float(options(project).get("jev_router_escalate_after") or 3)))
    except (TypeError, ValueError):
        return 3


def record_failure(payload: dict[str, Any], project: Path, agent_id: str) -> None:
    records = audit_records(payload)
    route = _route_for_agent(records, agent_id)
    if route is None:
        return
    audit(
        payload,
        {
            "kind": "tool_failure",
            "turn_id": payload.get("turn_id"),
            "agent_id": agent_id,
            "tool_use_id": payload.get("tool_use_id"),
            "tool_name": payload.get("tool_name"),
        },
    )
    catalog = load_catalog(project, host="codex")
    ascending = tuple(reversed([item.alias for item in catalog]))
    current = route.get("model")
    if current not in ascending or ascending.index(current) == len(ascending) - 1:
        return
    threshold = _escalate_after(project)
    path = logs.session_file(project, TOOL, str(payload.get("session_id") or ""))
    escalation = {
        "session_id": str(payload.get("session_id") or ""),
        "kind": "escalation",
        "turn_id": payload.get("turn_id"),
        "agent_id": agent_id,
        "from": current,
        "to": ascending[ascending.index(current) + 1],
        "effort": route.get("effort"),
        "files": [item for item in route.get("files") or () if isinstance(item, str)],
    }

    def ready(existing: list[dict[str, Any]]) -> bool:
        failures = sum(
            record.get("kind") == "tool_failure" and record.get("agent_id") == agent_id
            for record in existing
        )
        already = any(
            record.get("kind") == "escalation" and record.get("agent_id") == agent_id
            for record in existing
        )
        return failures >= threshold and not already and bool(escalation["files"])

    if logs.append_if(path, escalation, ready):
        router.outcome_mode(
            request(
                payload,
                project,
                record={
                    "turn_id": payload.get("turn_id"),
                    "errors": threshold,
                    "escalations": [
                        {
                            "from": escalation["from"],
                            "to": escalation["to"],
                            "effort": escalation["effort"],
                            "files": escalation["files"],
                        }
                    ],
                    "denials": 0,
                },
            )
        )


def post_tool_use(payload: dict[str, Any], project: Path) -> None:
    tool_name = str(payload.get("tool_name") or "")
    if is_spawn_tool(tool_name):
        agent_id = _agent_id(payload.get("tool_response"))
        if agent_id:
            audit(
                payload,
                {
                    "kind": "agent_link",
                    "turn_id": payload.get("turn_id"),
                    "tool_use_id": str(payload.get("tool_use_id") or ""),
                    "agent_id": agent_id,
                },
            )
        return
    agent_id = payload.get("agent_id")
    raw = payload.get("tool_input")
    if not isinstance(agent_id, str) or not isinstance(raw, dict) or not _failed(payload.get("tool_response")):
        return
    command = raw.get("command")
    if not isinstance(command, str):
        return
    targets = patch_targets(command) if tool_name == "apply_patch" else shell_targets(command)
    if targets:
        record_failure(payload, project, agent_id)


def pre_tool_use(payload: dict[str, Any], project: Path) -> dict[str, Any]:
    tool_name = str(payload.get("tool_name") or "")
    if is_spawn_tool(tool_name):
        return route_spawn(payload, project)
    if tool_name in ("apply_patch", "Bash"):
        return guard_write(payload, project)
    return {}


def is_spawn_tool(tool_name: str) -> bool:
    normalized = tool_name.lower().replace("::", ".")
    return normalized in ("spawn_agent", "collaborationspawn_agent", "agent") or normalized.endswith(".spawn_agent")


def dispatch(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    try:
        project = project_dir(payload.get("cwd"))
        if enabled(project) or skills_enabled(project):
            try:
                observe(payload)
            except Exception:
                pass
        event = payload.get("hook_event_name")
        if event == "SessionStart":
            return session_start(payload, project)
        if event == "UserPromptSubmit":
            return prompt_submit(payload, project)
        if event == "PreToolUse":
            return pre_tool_use(payload, project)
        if event == "PostToolUse" and enabled(project):
            post_tool_use(payload, project)
    except Exception as error:
        try:
            logs.append(
                logs.session_file(project_dir(payload.get("cwd")), TOOL, str(payload.get("session_id") or "")),
                {"kind": "adapter_error", "error": str(error)[:500]},
                locked=True,
            )
        except Exception:
            pass
    return {}


def main() -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        answer = dispatch(payload)
    except Exception:
        answer = {}
    sys.stdout.buffer.write(json.dumps(answer, separators=(",", ":")).encode("utf-8"))


if __name__ == "__main__":
    main()
