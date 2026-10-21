"""Per-session JSONL logs: `<project>/.optim-jev/logs/<tool>/<session_id>.jsonl`."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .paths import data_root

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def tool_dir(project_dir: str | os.PathLike[str], tool: str) -> Path:
    return data_root(project_dir) / "logs" / tool


def session_file(project_dir: str | os.PathLike[str], tool: str, session_id: str) -> Path:
    return tool_dir(project_dir, tool) / f"{_UNSAFE.sub('-', session_id or 'unknown')}.jsonl"


@contextmanager
def _append_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    if os.name == "nt":
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(lock_path, flags)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
        finally:
            os.close(fd)
        lock = open(lock_path, "r+b", buffering=0)
    else:
        lock = open(lock_path, "a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            for _ in range(500):
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
            else:
                raise TimeoutError(f"timed out locking {path}")
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked and os.name == "nt":
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        elif locked:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _line(record: dict[str, Any]) -> str:
    return json.dumps(
        {"ts": round(time.time()), **record},
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"


def _append_unlocked(path: Path, line: str) -> None:
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(line.encode("utf-8"))
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def append(path: Path, record: dict[str, Any], *, locked: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = _line(record)
    if locked:
        with _append_lock(path):
            _append_unlocked(path, line)
        return
    # Preserve Claude's original text-mode JSONL bytes and failure behavior.
    with open(path, "a", encoding="utf-8") as file:
        file.write(line)


def append_if(
    path: Path,
    record: dict[str, Any],
    predicate: Callable[[list[dict[str, Any]]], bool],
) -> bool:
    """Append only when `predicate` accepts the records while all writers are locked."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _append_lock(path):
        if not predicate(_read_unlocked(path)):
            return False
        _append_unlocked(path, _line(record))
    return True


def _read_unlocked(path: Path) -> list[dict[str, Any]]:
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


def read(path: Path, *, locked: bool = False) -> list[dict[str, Any]]:
    if locked and path.exists():
        with _append_lock(path):
            return _read_unlocked(path)
    return _read_unlocked(path)


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
