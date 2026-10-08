"""Per-session persistence of CompactionMemory, tied to the transcript it describes.

Files live in `<project>/.optim-jev/logs/jev_compacter/<session_id>.jsonl`, one snapshot line per
save (the last valid line is the memory), and only as long as their transcript: `load` discards a
file whose transcript is gone, and `sweep` removes all such files.

`messages` must be the session's current conversation path, not every entry in the transcript:
rewound or abandoned branches can stay in the file. Remembered answers are kept only for tool
calls on that path with the same tool and input (fingerprint), so decisions about calls the
session no longer has are dropped on the next save instead of accumulating.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ...core import logs
from .types import CallAnswer, CompactionMemory, Message, ToolUse

SCHEMA = 1
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def store_dir(project_dir: str | os.PathLike[str]) -> Path:
    return logs.tool_dir(project_dir, "jev_compacter")


def fingerprint(tool: ToolUse) -> str:
    payload = json.dumps([tool.tool, tool.input], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _file_for(directory: Path, session_id: str) -> Path:
    return directory / f"{_UNSAFE.sub('-', session_id)}.jsonl"


def _read(path: Path) -> dict[str, Any] | None:
    """The newest snapshot in the file."""
    return next((r for r in reversed(logs.read(path)) if r.get("schema") == SCHEMA), None)


def _fingerprints(messages: Sequence[Message]) -> dict[str, str]:
    return {t.tool_use_id: fingerprint(t) for m in messages for t in m.tool_uses}


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def load(
    directory: Path, session_id: str, transcript_path: str, messages: Sequence[Message]
) -> CompactionMemory:
    """Memory for this session, reconciled against the current conversation path."""
    path = _file_for(directory, session_id)
    if not os.path.exists(transcript_path):
        _unlink(path)
        return CompactionMemory()
    data = _read(path)
    if (
        data is None
        or data.get("session_id") != session_id
        or not _same_path(str(data.get("transcript_path", "")), transcript_path)
    ):
        return CompactionMemory()

    current = _fingerprints(messages)
    answers: dict[str, CallAnswer] = {}
    raw_answers = data.get("answers")
    for key, entry in (raw_answers.items() if isinstance(raw_answers, dict) else ()):
        if not isinstance(entry, dict):
            continue

        # Tool call answers: need fingerprint match
        if key in current and current.get(key) != entry.get("fp"):
            continue

        keep_call, keep_result = entry.get("keep_call"), entry.get("keep_result")
        if isinstance(keep_call, (int, float)) and isinstance(keep_result, (int, float)):
            answers[key] = CallAnswer(float(keep_call), float(keep_result))
        # Text answers (keyed by "text_<index>") don't need fingerprint validation
        elif key.startswith("text_") and isinstance(keep_call, (int, float)):
            answers[key] = CallAnswer(float(keep_call), 1.0)

    baseline = data.get("baseline_tokens")
    if not isinstance(baseline, int) or isinstance(baseline, bool) or baseline < 0:
        baseline = None
    return CompactionMemory(baseline, answers)


def save(
    directory: Path,
    session_id: str,
    transcript_path: str,
    messages: Sequence[Message],
    memory: CompactionMemory,
) -> None:
    """Appends a snapshot of the memory; answers for calls not on the current path are not stored."""
    current = _fingerprints(messages)
    answers_out = {}
    for key, a in memory.answers.items():
        if key.startswith("text_"):
            # Text answers: no fingerprint needed, just store the score
            answers_out[key] = {"keep_call": a.keep_call, "keep_result": a.keep_result}
        elif key in current:
            # Tool call answers: include fingerprint to validate after message changes
            answers_out[key] = {"fp": current[key], "keep_call": a.keep_call, "keep_result": a.keep_result}

    data = {
        "schema": SCHEMA,
        "session_id": session_id,
        "transcript_path": os.path.abspath(transcript_path),
        "baseline_tokens": memory.baseline_tokens,
        "answers": answers_out,
    }
    logs.append(_file_for(directory, session_id), data)


def read_all(directory: Path, session_id: str) -> list[dict[str, Any]]:
    return logs.read(_file_for(directory, session_id))


def log_outcome(directory: Path, session_id: str, record: dict[str, Any]) -> None:
    """A compaction's raw numbers; it has no `schema`, so `load` never mistakes it for memory."""
    logs.append(_file_for(directory, session_id), record)


def sweep(directory: Path) -> int:
    """Deletes store files whose transcript no longer exists."""
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.glob("*.jsonl"):
        data = _read(path)
        if data is None:
            continue  # outcomes only, no snapshot to tie it to a transcript
        transcript = data.get("transcript_path")
        if not isinstance(transcript, str) or not os.path.exists(transcript):
            _unlink(path)
            removed += 1
    return removed
