"""The skill roster: name, description, source and folder of every SKILL.md in scope.

Cached in `.optim-jev/jev_skills/index.json`, rebuilt when any SKILL.md in scope is added,
removed or modified, so a prompt does not re-read every folder.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from ...core.paths import data_root

INDEX_FILE = "index.json"
MAX_DESCRIPTION_CHARS = 600
_FRONT = re.compile(r"^---\s*\n(.*?)\n---", re.S)
_NAME = re.compile(r"^name:\s*(.+)$", re.M)
# Indented continuation lines too, so YAML block scalars (description: >) work.
_DESC = re.compile(r"^description:[ \t]*(.*(?:\n[ \t]+.*)*)", re.M)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    source: str  # project | user | plugin:<name>
    dir: str


def skills_dir(project_dir: str | os.PathLike[str]) -> Path:
    return data_root(project_dir) / "jev_skills"


def _home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _plugin_roots() -> list[tuple[str, Path]]:
    try:
        data = json.loads((_home() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    roots = []
    for key, installs in (data.get("plugins") or {}).items():
        for install in installs if isinstance(installs, list) else []:
            path = install.get("installPath") if isinstance(install, dict) else None
            if isinstance(path, str):
                roots.append((key.split("@", 1)[0], Path(path)))
    return roots


def sources(project_dir: str | os.PathLike[str], is_global: bool) -> list[tuple[str, str, Path]]:
    """(source, name prefix, skills folder) in priority order: project first."""
    found = [("project", "", Path(project_dir) / ".claude" / "skills")]
    if is_global:
        found.append(("user", "", _home() / "skills"))
        found += [(f"plugin:{name}", f"{name}:", root / "skills") for name, root in _plugin_roots()]
    return found


def parse(text: str) -> tuple[str, str] | None:
    front = _FRONT.match(text)
    body = front.group(1) if front else ""
    name, desc = _NAME.search(body), _DESC.search(body)
    if not name or not desc:
        return None
    description = " ".join(re.sub(r"^[>|][-+]?", "", desc.group(1).strip()).split()).strip("\"'")
    return name.group(1).strip().strip("\"'"), description[:MAX_DESCRIPTION_CHARS]


def _files(project_dir: str | os.PathLike[str], is_global: bool) -> list[tuple[str, str, Path]]:
    files = []
    for source, prefix, folder in sources(project_dir, is_global):
        for md in sorted(folder.glob("*/SKILL.md")) if folder.is_dir() else []:
            files.append((source, prefix, md))
    return files


def load(project_dir: str | os.PathLike[str], is_global: bool) -> list[Skill]:
    files = _files(project_dir, is_global)
    signature = [[str(md), md.stat().st_mtime_ns] for _, _, md in files]
    cache = skills_dir(project_dir) / INDEX_FILE
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("global") == is_global and cached.get("signature") == signature:
            return [Skill(**s) for s in cached["skills"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    skills: dict[str, Skill] = {}
    for source, prefix, md in files:
        parsed = parse(md.read_text(encoding="utf-8", errors="replace"))
        if parsed:
            name = prefix + parsed[0]
            skills.setdefault(name, Skill(name, parsed[1], source, str(md.parent)))
    roster = list(skills.values())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"global": is_global, "signature": signature, "skills": [asdict(s) for s in roster]}, indent=1),
        encoding="utf-8",
    )
    return roster
