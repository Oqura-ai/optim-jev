"""The skill roster: name, description, source and folder of every SKILL.md in scope.

Cached in `.optim-jev/jev_skills/index.json`, rebuilt when any SKILL.md in scope is added,
removed or modified, so a prompt does not re-read every folder.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
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


@dataclass(frozen=True)
class SkillRoot:
    source: str
    prefix: str
    path: Path


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


def sources(project_dir: str | os.PathLike[str], is_global: bool) -> list[SkillRoot]:
    """Claude skill roots in priority order; callers for other hosts pass their own roots to `load`."""
    found = [SkillRoot("project", "", Path(project_dir) / ".claude" / "skills")]
    if is_global:
        found.append(SkillRoot("user", "", _home() / "skills"))
        found += [SkillRoot(f"plugin:{name}", f"{name}:", root / "skills") for name, root in _plugin_roots()]
    return found


def parse(text: str) -> tuple[str, str] | None:
    front = _FRONT.match(text)
    body = front.group(1) if front else ""
    name, desc = _NAME.search(body), _DESC.search(body)
    if not name or not desc:
        return None
    description = " ".join(re.sub(r"^[>|][-+]?", "", desc.group(1).strip()).split()).strip("\"'")
    return name.group(1).strip().strip("\"'"), description[:MAX_DESCRIPTION_CHARS]


def _files(
    project_dir: str | os.PathLike[str],
    is_global: bool,
    roots: Sequence[SkillRoot] | None = None,
) -> list[tuple[str, str, Path]]:
    files = []
    for root in roots if roots is not None else sources(project_dir, is_global):
        for md in sorted(root.path.glob("*/SKILL.md")) if root.path.is_dir() else []:
            files.append((root.source, root.prefix, md))
    return files


def load(
    project_dir: str | os.PathLike[str],
    is_global: bool,
    roots: Sequence[SkillRoot] | None = None,
    *,
    host: str = "claude",
) -> list[Skill]:
    files = _files(project_dir, is_global, roots)
    normalized_host = host.strip().lower()
    signature = (
        [[str(markdown), markdown.stat().st_mtime_ns] for _, _, markdown in files]
        if normalized_host in ("", "claude")
        else [
            [source, prefix, str(markdown), markdown.stat().st_mtime_ns]
            for source, prefix, markdown in files
        ]
    )
    cache_name = INDEX_FILE if normalized_host in ("", "claude") else f"index.{normalized_host}.json"
    cache = skills_dir(project_dir) / cache_name
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
