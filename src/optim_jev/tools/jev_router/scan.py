"""What init shows the writer: the tree (names, counts, sizes, `depth` levels deep) and a short digest of its main files."""

from __future__ import annotations

import os
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = frozenset(
    {
        ".git", ".optim-jev", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
        "dist", "build", "out", "target", ".next", ".nuxt", ".turbo", ".cache", "coverage",
        ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".gradle",
    }
)
MAX_FILES = 200_000
# Per directory, files listed one by one before the rest are summarised.
MAX_LISTED_FILES = 40


@dataclass(frozen=True)
class Entry:
    path: str  # directories end with "/"
    files: int
    size: int

    @property
    def is_dir(self) -> bool:
        return self.path.endswith("/")


def _skipped(rel: str) -> bool:
    return any(part in SKIP_DIRS for part in rel.split("/")[:-1])


def _git_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, capture_output=True, timeout=30, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root: Path) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        base = Path(dirpath).relative_to(root).as_posix()
        files.extend(f if base == "." else f"{base}/{f}" for f in sorted(filenames))
        if len(files) >= MAX_FILES:
            break
    return files


def list_files(root: Path) -> list[str]:
    files = _git_files(root)
    if files is None:
        files = _walk_files(root)
    return [f for f in files[:MAX_FILES] if not _skipped(f)]


def scan(root: str | os.PathLike[str], depth: int = 2) -> list[Entry]:
    """Directories and files at most `depth` levels down, with subtree file counts and sizes."""
    base = Path(root)
    depth = max(1, depth)
    dirs: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    files: list[Entry] = []
    for rel in list_files(base):
        try:
            size = (base / rel).stat().st_size
        except OSError:
            continue
        parts = rel.split("/")
        for level in range(1, min(depth, len(parts) - 1) + 1):
            stats = dirs["/".join(parts[:level]) + "/"]
            stats[0] += 1
            stats[1] += size
        if len(parts) <= depth:
            files.append(Entry(rel, 1, size))
    entries = [Entry(p, n, s) for p, (n, s) in dirs.items()] + files
    return sorted(entries, key=lambda e: e.path)


DIGEST_CHARS = 10_000  # about 2.5k tokens
DIGEST_FILES_PER_FOLDER = 3
MAX_DIGEST_FILE_BYTES = 200_000
READ_BYTES = 8_192
MAX_SYMBOLS = 8
MAX_LINE_CHARS = 200
CODE_SUFFIXES = frozenset(
    ".py .ts .tsx .js .jsx .mjs .go .rs .java .kt .rb .php .cs .c .h .cpp .swift .sh .sql .md .toml".split()
)
_SYMBOL = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:def|class|function|interface|type|func|fn|struct|enum|trait)\s+([A-Za-z]\w*)",
    re.MULTILINE,
)
_EXPORTED = re.compile(r"^export\s+(?:const|let|var)\s+([A-Za-z]\w*)", re.MULTILINE)
_PY_DOC = re.compile(r'^\s*(?:#.*\n\s*)*(?:"""|\'\'\')\s*(.+)', re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"^\s*/\*\*?\s*\n?\s*\*?\s*([^\n*][^\n]*)")
_LINE_COMMENT = re.compile(r"^\s*(?://|#)\s?(?![!:\-*]|\s*(?:eslint|ts-|@ts|noqa|type:|-\*-|use strict))(.{12,})")


def _first_line(text: str, suffix: str) -> str:
    if suffix == ".md":
        heading = re.search(r"^#{1,3}\s+(.+)", text, re.MULTILINE)
        return heading.group(1).strip() if heading else ""
    doc = _PY_DOC.match(text) if suffix == ".py" else _BLOCK_COMMENT.match(text)
    if doc:
        return doc.group(1).strip().rstrip('"\'*/ ')
    for line in text.splitlines()[:12]:
        comment = _LINE_COMMENT.match(line)
        if comment:
            return comment.group(1).strip()
    return ""


def _describe(base: Path, rel: str) -> str:
    suffix = Path(rel).suffix.lower()
    try:
        with open(base / rel, "rb") as f:
            text = f.read(READ_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""
    summary = _first_line(text, suffix)
    names: list[str] = []
    if suffix != ".md":
        for name in (*_SYMBOL.findall(text), *_EXPORTED.findall(text)):
            if not name.startswith("_") and name not in names:
                names.append(name)
    parts = [summary] if summary else []
    if names:
        parts.append("defines " + ", ".join(names[:MAX_SYMBOLS]))
    return f"{rel}  {' · '.join(parts)}"[:MAX_LINE_CHARS] if parts else ""


def digest(root: str | os.PathLike[str], budget: int = DIGEST_CHARS) -> list[str]:
    """What the biggest files of each folder hold (first comment, top-level names; not contents), biggest folders first."""
    base = Path(root)
    folders: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for rel in list_files(base):
        if Path(rel).suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            size = (base / rel).stat().st_size
        except OSError:
            continue
        if 0 < size <= MAX_DIGEST_FILE_BYTES:
            folders[rel.rpartition("/")[0]].append((size, rel))
    lines: list[str] = []
    used = 0
    for _, files in sorted(folders.items(), key=lambda kv: -sum(s for s, _ in kv[1])):
        for _, rel in sorted(files, reverse=True)[:DIGEST_FILES_PER_FOLDER]:
            line = _describe(base, rel)
            if line and used + len(line) <= budget:
                lines.append(line)
                used += len(line)
    return sorted(lines)


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def listing(entries: list[Entry]) -> list[str]:
    """One line per entry, the largest files of a crowded directory listed and the rest summarised."""
    by_parent: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        if not e.is_dir:
            by_parent[e.path.rpartition("/")[0]].append(e)
    shown = {
        e.path
        for group in by_parent.values()
        for e in sorted(group, key=lambda x: x.size, reverse=True)[:MAX_LISTED_FILES]
    }
    lines: list[str] = []
    for e in entries:
        if e.is_dir:
            lines.append(f"{e.path}  {e.files} files, {_size(e.size)}")
            hidden = [f for f in by_parent.get(e.path.rstrip("/"), []) if f.path not in shown]
            if hidden:
                lines.append(f"{e.path}…  (+{len(hidden)} smaller files not listed)")
        elif e.path in shown:
            lines.append(f"{e.path}  {_size(e.size)}")
    root_hidden = [f for f in by_parent.get("", []) if f.path not in shown]
    if root_hidden:
        lines.append(f"(+{len(root_hidden)} smaller top-level files not listed)")
    return lines
