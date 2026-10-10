"""Claude Code bridge for the model router: one JSON request on stdin, one JSON answer on stdout.

    python -m optim_jev.tools.jev_router.tool <mode>

render     {session_model}                       -> {section, rules, tiers, current, has_rules}
spawn      {session_id, session_model, description, prompt, escalated}
           -> {model, files, appendix, toast, source, escalated, jev_failed}
scan       {session_model, directive, depth, force} -> {system, prompt, paths, models} | {refused}
validate   {}                                    -> {problems}
init_save  {session_model, directive, depth, reply, checks} -> {text, rules, count}
outcome    {session_id, record}                  -> {}
why        {session_id}                          -> {text}
stats      {}                                    -> {text}

Every request also carries project_dir and options (this tool reads the `jev_router_` keys).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ...core import pricing
from ..jev_compacter.jev import JevClient
from . import context as context_mod, journal, render, rules as rules_mod, scan as scan_mod, writer
from .catalog import Ladder, build_ladder, load_catalog, save_catalog, with_checks
from .config import RouterConfig
from .policy import appendix, files_json, mentioned_files, pick, toast

OPTION_PREFIX = "jev_router_"


def _config(request: dict[str, Any]) -> RouterConfig:
    raw = request.get("options")
    raw = raw if isinstance(raw, dict) else {}
    return RouterConfig.from_mapping({k[len(OPTION_PREFIX):]: v for k, v in raw.items() if k.startswith(OPTION_PREFIX)})


def _context(request: dict[str, Any], with_learned: bool = False) -> tuple[RouterConfig, rules_mod.Rules, Ladder]:
    config = _config(request)
    project = request["project_dir"]
    catalog_aliases = tuple(reversed([m.alias for m in load_catalog(project)]))
    rules = rules_mod.load(project, catalog_aliases)
    learned = journal.learned(journal.read(project, str(request.get("session_id") or ""))) if with_learned else {}
    ladder = build_ladder(str(request.get("session_model") or ""), rules.exclude, config.is_capped, learned, project)
    return config, rules, ladder


def _jev(config: RouterConfig) -> JevClient:
    return JevClient(model=config.model, base_url=config.base_url, timeout=30.0)


def _rules_table(rules: rules_mod.Rules) -> dict[str, Any]:
    return {p: {"write": list(r.write), "delete": list(r.delete)} for p, r in rules.paths.items()}


def render_mode(request: dict[str, Any]) -> dict[str, Any]:
    _, rules, ladder = _context(request, with_learned=True)
    return {
        "section": render.section(ladder),
        "rules": _rules_table(rules),
        "tiers": list(ladder.ascending),
        "current": ladder.current,
        "has_rules": bool(rules.paths),
    }


def spawn_mode(request: dict[str, Any]) -> dict[str, Any]:
    """A subagent's model and effort. When Jev's input stays over budget, answers `ask_claude` (a prompt)
    and logs nothing; the hook asks Claude and calls again with `decided`."""
    config, rules, ladder = _context(request)
    project = request["project_dir"]
    description = str(request.get("description") or "")
    prompt = str(request.get("prompt") or "")
    escalated = request.get("escalated") if isinstance(request.get("escalated"), dict) else {}
    recent = [str(t) for t in request.get("recent_inputs") or () if isinstance(t, str)]
    decided = request.get("decided") if isinstance(request.get("decided"), dict) else None
    named = [f.path for f in mentioned_files(f"{description}\n{prompt}", rules, project)]
    context = context_mod.relevant(context_mod.load(project), named)
    jev = _jev(config)
    result = pick(
        description, prompt, rules, context, ladder, jev, project, escalated,
        recent=recent, budget=config.max_input_tokens, decided=decided,
    )
    if result.ask_claude is not None:
        return {"ask_claude": result.ask_claude, "reason": result.jev_failed}
    journal.append(
        project,
        str(request.get("session_id") or ""),
        {
            "kind": "spawn",
            "current": ladder.current,
            "description": description[:120],
            "model": result.model,
            "effort": result.effort,
            "source": result.source,
            "allowed": list(result.allowed),
            "probabilities": result.probabilities,
            "effort_probabilities": result.effort_probabilities,
            "escalated": result.escalated,
            "jev_failed": result.jev_failed,
            "files": files_json((*result.files, *result.blocked)),
            "jev_input_tokens_est": result.input_tokens_est,
            "trimmed": result.trimmed,
            "jev": jev.usage(),
        },
    )
    return {
        "model": result.model,
        "effort": result.effort,
        "files": [f.path for f in result.files],
        "appendix": appendix(result, context, ladder),
        "toast": toast(description, result),
        "source": result.source,
        "escalated": result.escalated,
        "jev_failed": result.jev_failed,
    }


def scan_mode(request: dict[str, Any]) -> dict[str, Any]:
    config, rules, ladder = _context(request)
    if rules.paths and not request.get("force"):
        return {
            "refused": f"jev-router: this project already has {len(rules.paths)} rule(s). Ask Claude to change them, "
            "or run /jev-route init --force to draft them again (rules.json and RULES.md are kept as *.bak)."
        }
    depth = int(request.get("depth") or config.depth)
    entries = scan_mod.scan(request["project_dir"], depth)
    return {
        "system": writer.system_prompt(depth, ladder),
        "prompt": writer.user_prompt(
            entries, str(request.get("directive") or ""), ladder, scan_mod.digest(request["project_dir"])
        ),
        "paths": len(entries),
        # Every catalog model, unavailable ones too, so a re-init checks them again.
        "models": [{"alias": m.alias, "id": m.id} for m in load_catalog(request["project_dir"])],
    }


def init_save_mode(request: dict[str, Any]) -> dict[str, Any]:
    project = request["project_dir"]
    catalog = with_checks(load_catalog(project), request.get("checks"))
    save_catalog(project, catalog)
    config, old, ladder = _context(request)
    depth = int(request.get("depth") or config.depth)
    entries = scan_mod.scan(project, depth)
    tiers = {m.alias: m.tier for m in catalog}
    rules, context = writer.parse_reply(str(request.get("reply") or ""), entries, ladder, tiers)
    rules = rules_mod.Rules(rules.paths, old.exclude)
    path = rules_mod.save(project, rules)
    context_path = path.with_name(context_mod.CONTEXT_FILE)
    rules_mod.backup(context_path)
    rules_mod.write_atomic(context_path, context_mod.markdown(context))
    facts = len(context.general) + sum(len(f) for f in context.paths.values())
    models = ", ".join(
        f"{m.alias} {'✓ ' + m.id if m.available and m.id else '✓ (id learned at runtime)' if m.available else '✗ unavailable'}"
        for m in catalog
    )
    text = "\n".join(
        [
            f"jev-router: {len(rules.paths)} rules → {path}",
            f"            {facts} codebase facts → {context_path}",
            f"            models: {models}",
            "",
            "```",
            *(render.rule_rows(list(rules.paths.values()), ladder) or ["(no rules: every path is open to every model)"]),
            "```",
            "",
            "Only the rows and RULES.md sections for the files a subagent's prompt names reach Jev and that subagent.",
            "Edit rules.json and RULES.md freely; re-running init backs both up to *.bak.",
        ]
    )
    return {"text": text, "rules": _rules_table(rules), "count": len(rules.paths)}


def validate_mode(request: dict[str, Any]) -> dict[str, Any]:
    project = request["project_dir"]
    known = tuple(reversed([m.alias for m in load_catalog(project)]))
    return {"problems": rules_mod.validate(project, known)}


def outcome_mode(request: dict[str, Any]) -> dict[str, Any]:
    record = request.get("record")
    if isinstance(record, dict):
        journal.append(request["project_dir"], str(request.get("session_id") or ""), {"kind": "outcome", **record})
    return {}


def why_mode(request: dict[str, Any]) -> dict[str, Any]:
    session_id = str(request.get("session_id") or "")
    return {"text": journal.why(journal.read(request["project_dir"], session_id), session_id)}


def stats_mode(request: dict[str, Any]) -> dict[str, Any]:
    project = request["project_dir"]
    session_id = str(request.get("session_id") or "")
    records, claude = journal.read(project, session_id), pricing.claude_log(project, session_id)
    return {"text": journal.stats(records, load_catalog(project), claude)}


HANDLERS = {
    "render": render_mode,
    "spawn": spawn_mode,
    "scan": scan_mode,
    "validate": validate_mode,
    "init_save": init_save_mode,
    "outcome": outcome_mode,
    "why": why_mode,
    "stats": stats_mode,
}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in HANDLERS:
        sys.exit(f"usage: python -m optim_jev.tools.jev_router.tool {{{'|'.join(HANDLERS)}}}")
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(HANDLERS[mode](request), ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
