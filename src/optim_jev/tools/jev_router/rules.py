"""`.optim-jev/jev_router/rules.json`: which models may write or delete each path, and why.

Only the rows of the files a plan names are ever sent to a model or to Jev.

Keys are project-relative POSIX paths; directories end with `/`. A path takes the rule of its
nearest listed ancestor (itself included); a path under no rule is open to every model.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.paths import data_root

SCHEMA = 1
RULES_FILE = "rules.json"
MAX_WHY_CHARS = 80
# Shared files stay committable even though `.optim-jev/` is otherwise ignored.
GITIGNORE = "*\n!.gitignore\n!jev_router/\njev_router/*\n!jev_router/rules.json\n!jev_router/RULES.md\n"


@dataclass(frozen=True)
class Rule:
    path: str
    write: tuple[str, ...]
    delete: tuple[str, ...]
    why: str = ""


@dataclass(frozen=True)
class Rules:
    paths: dict[str, Rule]
    exclude: tuple[str, ...] = ()


def router_dir(project_dir: str | os.PathLike[str]) -> Path:
    return data_root(project_dir) / "jev_router"


def relative(path: str, project_dir: str | os.PathLike[str]) -> str:
    """`path` relative to the project in POSIX form; one outside it keeps a leading `../`."""
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, project_dir)
        except ValueError:  # another drive
            return path.replace("\\", "/")
    rel = path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _key(path: str) -> str:
    return path.casefold() if os.name == "nt" else path


def resolve(rules: Rules, rel: str) -> Rule | None:
    """The rule of `rel`'s nearest listed ancestor, itself first."""
    index = {_key(p): r for p, r in rules.paths.items()}
    probe = rel.rstrip("/")
    if _key(rel) in index:
        return index[_key(rel)]
    while probe:
        hit = index.get(_key(probe + "/")) or index.get(_key(probe))
        if hit:
            return hit
        probe = probe.rpartition("/")[0]
    return None


def _models(raw: Any, known: tuple[str, ...]) -> tuple[str, ...] | None:
    if not isinstance(raw, list):
        return None
    return tuple(a for a in known if a in raw)


def parse(data: Any, known: tuple[str, ...]) -> Rules:
    """Rules from JSON data; unknown models, bad entries and overlong text are dropped or cut."""
    if not isinstance(data, dict):
        return Rules({})
    paths: dict[str, Rule] = {}
    raw_paths = data.get("paths")
    for path, entry in (raw_paths.items() if isinstance(raw_paths, dict) else ()):
        if not isinstance(path, str) or not path.strip() or not isinstance(entry, dict):
            continue
        write = _models(entry.get("write"), known)
        if write is None:
            continue
        delete = _models(entry.get("delete"), known)
        why = entry.get("why")
        key = relative(path.strip(), ".")
        paths[key] = Rule(
            key,
            write,
            write if delete is None else delete,
            why.strip()[:MAX_WHY_CHARS] if isinstance(why, str) else "",
        )
    models = data.get("models")
    exclude = models.get("exclude") if isinstance(models, dict) else None
    return Rules(
        dict(sorted(paths.items())),
        tuple(a for a in (exclude if isinstance(exclude, list) else ()) if isinstance(a, str)),
    )


def load(project_dir: str | os.PathLike[str], known: tuple[str, ...]) -> Rules:
    try:
        text = (router_dir(project_dir) / RULES_FILE).read_text(encoding="utf-8")
        return parse(json.loads(text), known)
    except (OSError, ValueError):
        return Rules({})


def to_json(rules: Rules) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "paths": {
            p: {
                "write": list(r.write),
                **({} if r.delete == r.write else {"delete": list(r.delete)}),
                "why": r.why,
            }
            for p, r in rules.paths.items()
        },
    }
    if rules.exclude:
        data["models"] = {"exclude": list(rules.exclude)}
    return data


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(project_dir: str | os.PathLike[str], rules: Rules) -> Path:
    root = data_root(project_dir)
    ignore = root / ".gitignore"
    # Only the ignore file this plugin wrote is widened; an edited one is left alone.
    if ignore.read_text(encoding="utf-8").strip() == "*":
        ignore.write_text(GITIGNORE, encoding="utf-8")
    path = router_dir(project_dir) / RULES_FILE
    backup(path)
    write_atomic(path, json.dumps(to_json(rules), indent=2, ensure_ascii=False) + "\n")
    return path


def backup(path: Path) -> None:
    if path.exists():
        os.replace(path, path.with_name(path.name + ".bak"))
