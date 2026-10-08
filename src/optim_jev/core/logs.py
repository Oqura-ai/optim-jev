"""Per-session JSONL logs: `<project>/.optim-jev/logs/<tool>/<session_id>.jsonl`."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .paths import data_root

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def tool_dir(project_dir: str | os.PathLike[str], tool: str) -> Path:
    return data_root(project_dir) / "logs" / tool


def session_file(project_dir: str | os.PathLike[str], tool: str, session_id: str) -> Path:
    return tool_dir(project_dir, tool) / f"{_UNSAFE.sub('-', session_id or 'unknown')}.jsonl"


def append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": round(time.time()), **record}, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue  # a line cut short by a killed process
        if isinstance(item, dict):
            records.append(item)
    return records


def main() -> None:
    """`python -m optim_jev.core.logs claude`: {project_dir, session_id, records} -> {} (Claude's own usage)."""
    if sys.argv[1:] != ["claude"]:
        sys.exit("usage: python -m optim_jev.core.logs claude")
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    path = session_file(request["project_dir"], "claude", str(request.get("session_id") or ""))
    for record in request.get("records") or ():
        if isinstance(record, dict):
            append(path, record)
    sys.stdout.write("{}")


if __name__ == "__main__":
    main()
