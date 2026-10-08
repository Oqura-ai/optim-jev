"""`.optim-jev/jev_router/RULES.md`: unconventional facts about the codebase, by path.

Written once by init and edited by people afterwards; never regenerated from rules.json.
`## General` facts go with every plan; a `## <path>` section only when a planned file is under it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .rules import relative, router_dir

CONTEXT_FILE = "RULES.md"
GENERAL = "General"
_HEADING = re.compile(r"^##\s+`?([^`]+?)`?\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$")


@dataclass(frozen=True)
class Context:
    general: tuple[str, ...] = ()
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.general and not any(self.paths.values())


def parse(text: str) -> Context:
    general: list[str] = []
    paths: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            name = heading.group(1).strip()
            current = general if name.lower() == GENERAL.lower() else paths.setdefault(relative(name, "."), [])
            continue
        bullet = _BULLET.match(line)
        if bullet and current is not None:
            current.append(bullet.group(1))
    return Context(tuple(general), {p: tuple(f) for p, f in paths.items() if f})


def load(project_dir: str | os.PathLike[str]) -> Context:
    try:
        return parse((router_dir(project_dir) / CONTEXT_FILE).read_text(encoding="utf-8"))
    except OSError:
        return Context()


def _under(rel: str, key: str) -> bool:
    a, b = (rel.casefold(), key.casefold()) if os.name == "nt" else (rel, key)
    return a == b.rstrip("/") or a.startswith(b if b.endswith("/") else b + "/")


def relevant(context: Context, rel_paths: list[str]) -> list[str]:
    """General facts, then each section whose path is a planned file or one of its ancestors."""
    lines = [f"- {f}" for f in context.general]
    for key, facts in context.paths.items():
        if any(_under(rel, key) for rel in rel_paths):
            lines += [f"{key}:", *(f"- {f}" for f in facts)]
    return lines


def markdown(context: Context) -> str:
    lines = [
        "# Codebase context for model routing",
        "",
        "Written by `/jev-route init`; edit freely. `## General` facts go with every plan;",
        "a `## <path>` section is sent only when a planned file is under that path.",
        "",
        f"## {GENERAL}",
        "",
        *(f"- {f}" for f in context.general),
    ]
    for key, facts in context.paths.items():
        lines += ["", f"## {key}", "", *(f"- {f}" for f in facts)]
    return "\n".join(lines) + "\n"
