"""Init's writer: the prompt Claude gets for drafting rules.json and RULES.md, and the parse of its reply.

Jev answers probabilities only, so the text (paths, reasons, codebase context) is drafted by a
Claude model through the session's own client; the hook makes that call and hands the reply here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .catalog import Ladder
from .context import Context
from .render import ladder_lines
from .rules import Rule, Rules, parse, relative, resolve
from .scan import Entry, listing

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
MAX_FACTS = 12
MAX_FACT_CHARS = 200


def system_prompt(depth: int, ladder: Ladder) -> str:
    models = " | ".join(ladder.ascending)
    return f"""You draft the routing setup of optim-jev, a Claude Code plugin that sends each code edit to the cheapest model that will do it correctly.

You see the project's tree {depth} levels deep (names and sizes) and a digest of what its main files hold: each one's first comment and top-level names.

Answer with one JSON object and nothing else:
{{
  "paths": {{
    "<path from the tree>": {{"why": "<what this area holds and how demanding changes there are, at most 12 words>", "min": "<optional: {models} | none>", "delete": "<optional, same values>"}}
  }},
  "context": {{
    "general": ["<fact>"],
    "<path from the tree>": ["<fact about that path>"]
  }}
}}

"paths" (rules.json; only the rows of files being edited are ever shown to a model):
- Define the project's scopes: its areas as directories, a file only when it differs from its directory. Use only paths that appear in the tree, exactly as written; directories end with "/". Never go deeper than {depth} levels.
- Every model may write in every scope. Leave "min" and "delete" out unless the person's directive restricts that path: "min" is then the weakest model allowed to write there (every stronger one too), "none" means no model may; "delete" only when deleting needs a stronger model than writing.
- "why" is read by the model that picks which model runs a task: say what the area is and how demanding changes there are ("pricing engine; subtle invariants", "thin request handlers", "docs and examples").
- A limit on which models may work in a path is always a "min" here, never a fact in "context".

"context" (RULES.md; general facts go with every task, a path's facts only when a file under it is edited):
- Only unconventional facts that no path rule can express: a kind of work that cuts across paths ("documentation work only by sonnet or cheaper"), hidden coupling between paths, invariants, generated code and its source, things never safe to touch, project conventions that break the usual ones.
- Never restate "paths": no model limit for a listed path, no repeat of a "why", no description of what a folder holds. At most {MAX_FACTS} facts in all; an empty object is fine.

The person's directive, when given, overrides your own judgment."""


def user_prompt(entries: list[Entry], directive: str, ladder: Ladder, digest: list[str] | None = None) -> str:
    parts = []
    if directive.strip():
        parts += ["Directive from the person:", directive.strip(), ""]
    parts += ["Models, strongest first:", *ladder_lines(ladder), "", "Project tree:", *listing(entries)]
    if digest:
        parts += ["", "What the main files hold:", *digest]
    return "\n".join(parts)


def _expand(level: Any, ladder: Ladder, tiers: dict[str, int]) -> list[str] | None:
    """Models at or above `level`; an unavailable level moves up to the next available one."""
    if level == "none":
        return []
    if not isinstance(level, str) or level not in tiers:
        return None
    return [a for a in ladder.ascending if ladder.tier(a) >= tiers[level]] or [ladder.aliases[0]]


def _key(path: str, valid: set[str]) -> str | None:
    key = relative(path.strip(), ".")
    if key not in valid and key + "/" in valid:
        key += "/"
    return key if key in valid else None


def _facts(raw: Any) -> list[str]:
    return [f.strip()[:MAX_FACT_CHARS] for f in (raw if isinstance(raw, list) else ()) if isinstance(f, str) and f.strip()]


def parse_reply(text: str, entries: list[Entry], ladder: Ladder, tiers: dict[str, int]) -> tuple[Rules, Context]:
    """Rules and context from the writer's reply; paths not in the tree are dropped. Raises ValueError."""
    body = _FENCE.sub("", text.strip())
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("the writer's reply holds no JSON object")
    data = json.loads(body[start : end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise ValueError("the writer's reply has no paths")
    valid = {e.path for e in entries}

    paths: dict[str, Any] = {}
    for path, entry in data["paths"].items():
        if not isinstance(entry, dict) or not isinstance(path, str):
            continue
        key = _key(path, valid)
        level = entry.get("min")
        write = list(ladder.ascending) if level is None else _expand(level, ladder, tiers)
        if key is None or write is None:
            continue
        delete = _expand(entry.get("delete"), ladder, tiers)
        paths[key] = {"write": write, "delete": write if delete is None else delete, "why": entry["why"] if isinstance(entry.get("why"), str) else ""}
    rules = parse({"paths": paths}, ladder.ascending)

    raw_context = data.get("context") if isinstance(data.get("context"), dict) else {}
    budget = MAX_FACTS
    general = _facts(raw_context.get("general"))[:budget]
    budget -= len(general)
    by_path: dict[str, tuple[str, ...]] = {}
    for path, facts in raw_context.items():
        key = _key(path, valid) if isinstance(path, str) and path != "general" else None
        kept = _facts(facts)[: max(0, budget)]
        if key and kept:
            by_path[key] = by_path.get(key, ()) + tuple(kept)
            budget -= len(kept)
    rules = Rules(_without_redundant(rules.paths, ladder.ascending), rules.exclude)
    return rules, _without_rule_facts(Context(tuple(general), dict(sorted(by_path.items()))), rules)


_MODEL_WORDS = re.compile(r"\b(haiku|sonnet|opus|cheaper|cheapest|stronger|strongest|weaker|weakest)\b", re.IGNORECASE)


def _without_rule_facts(context: Context, rules: Rules) -> Context:
    """RULES.md keeps what rules.json cannot say: drops facts that repeat a rule's reason, or that limit
    models for a path that has a rule (general facts may still name models: they cut across paths)."""
    whys = {r.why.casefold().rstrip(".") for r in rules.paths.values() if r.why}

    def keep(path: str | None, fact: str) -> bool:
        if fact.casefold().rstrip(".") in whys:
            return False
        return not (path is not None and resolve(rules, path) is not None and _MODEL_WORDS.search(fact))

    paths = {p: kept for p, facts in context.paths.items() if (kept := tuple(f for f in facts if keep(p, f)))}
    return Context(tuple(f for f in context.general if keep(None, f)), paths)


def _without_redundant(paths: dict[str, Rule], everyone: tuple[str, ...]) -> dict[str, Rule]:
    """Drops a rule that only repeats its nearest ancestor's models, or leaves every model open, without a reason."""
    kept: dict[str, Rule] = {}
    for path, rule in paths.items():
        if not rule.why and set(rule.write) >= set(everyone) and set(rule.delete) >= set(everyone):
            continue
        parent = path.rstrip("/").rpartition("/")[0]
        ancestor = None
        while parent and ancestor is None:
            ancestor = paths.get(parent + "/")
            parent = parent.rpartition("/")[0]
        if ancestor and not rule.why and (ancestor.write, ancestor.delete) == (rule.write, rule.delete):
            continue
        kept[path] = rule
    return kept
