from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from .config import CompactionConfig
from .types import FittedState, JevCompactionError, Message, ToolCall, ToolResult

STATE_CONTEXT = (
    "A coding assistant conversation is being compacted to free context. `history` is the "
    "whole conversation so far, oldest first; tool outputs are replaced by a short `result` "
    "note and long texts may be abridged. Each question asks whether one tool call, or the "
    "full output of that call, still needs to stay in the history verbatim, or whether one "
    "assistant text (quoted in the question) contributes to the coding logic. Whatever is not "
    "kept is deleted permanently, but the assistant can always re-run a tool or re-read a file."
)

INPUT_CHARS = (1000, 200, 60)
TEXT_HEAD = 400
TEXT_TAIL = 150

_TOKEN_PIECES = re.compile(r"[A-Za-z]+|[0-9]+|[^\sA-Za-z0-9]")
_WHITESPACE = re.compile(r"\s+")

HistoryEntry = dict[str, Any]


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def estimate_tokens(text: str) -> int:
    """Tokenizer-free estimate calibrated to land a little above Jev's reported counts."""
    tokens = 0.0
    for match in _TOKEN_PIECES.finditer(text):
        piece = match.group()
        first = piece[0]
        if "0" <= first <= "9":
            tokens += len(piece) / 2
        elif first.isascii() and first.isalpha():
            tokens += 1 + (len(piece) - 1) // 6
        else:
            tokens += 0.9
    return math.ceil(tokens)


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: max(0, limit - 1)]}…"


def _abridge(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail + 40:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n[… {omitted} chars omitted …]\n{text[-tail:]}"


def is_pinned(index: int, total: int, preserve_recent_messages: int) -> bool:
    return index == 0 or index >= total - preserve_recent_messages


def collect_tool_calls(messages: Sequence[Message], preserve_recent_messages: int) -> list[ToolCall]:
    """Pairs every tool_use with its tool_result; calls without a result are skipped."""
    results: dict[str, tuple[int, ToolResult]] = {}
    for index, message in enumerate(messages):
        for result in message.tool_results:
            results[result.tool_use_id] = (index, result)

    total = len(messages)
    calls: list[ToolCall] = []
    for call_index, message in enumerate(messages):
        for tool in message.tool_uses:
            found = results.get(tool.tool_use_id)
            if found is None:
                continue
            result_index, result = found
            calls.append(
                ToolCall(
                    id=f"t{len(calls) + 1}",
                    tool_use_id=tool.tool_use_id,
                    tool=tool.tool,
                    input=tool.input,
                    call_index=call_index,
                    result_index=result_index,
                    result_chars=len(result.text),
                    is_error=result.is_error,
                    pinned=is_pinned(call_index, total, preserve_recent_messages)
                    or is_pinned(result_index, total, preserve_recent_messages),
                )
            )
    return calls


def _input_text(tool_input: dict[str, Any], limit: int) -> str:
    try:
        text = to_json(tool_input)
    except (TypeError, ValueError):
        text = "[unserializable input]"
    return truncate(text, limit)


def _result_note(call: ToolCall) -> str:
    return f"{'error' if call.is_error else 'ok'}, {call.result_chars} chars (omitted)"


def _compact_call(call: ToolCall) -> str:
    parts = []
    for key, value in call.input.items():
        text = value if isinstance(value, str) else _input_text({key: value}, 200)
        parts.append(f"{key}={_WHITESPACE.sub(' ', text)}")
    status = "error" if call.is_error else "ok"
    return f"{call.id} {call.tool} {truncate(' '.join(parts), INPUT_CHARS[2])} → {status} {call.result_chars}ch"


def _merge_call_runs(
    history: Sequence[HistoryEntry], pinned: Callable[[HistoryEntry], bool]
) -> list[HistoryEntry]:
    def foldable(entry: HistoryEntry) -> bool:
        calls = entry.get("tool_calls")
        return not pinned(entry) and not entry["text"] and bool(calls) and isinstance(calls[0], str)

    merged: list[HistoryEntry] = []
    for entry in history:
        previous = merged[-1] if merged else None
        if previous and foldable(previous) and foldable(entry) and previous["role"] == entry["role"]:
            previous["tool_calls"] = [*previous["tool_calls"], *entry["tool_calls"]]
            continue
        merged.append(dict(entry))
    return merged


def _calls_by_message(calls: Sequence[ToolCall]) -> dict[int, list[ToolCall]]:
    by_message: dict[int, list[ToolCall]] = {}
    for call in calls:
        by_message.setdefault(call.call_index, []).append(call)
    return by_message


def _history_entries(
    messages: Sequence[Message], calls: Sequence[ToolCall], input_chars: int
) -> list[HistoryEntry]:
    by_message = _calls_by_message(calls)
    entries: list[HistoryEntry] = []
    for i, message in enumerate(messages):
        tool_calls = [
            {
                "id": call.id,
                "tool": call.tool,
                "input": _input_text(call.input, input_chars),
                "result": _result_note(call),
            }
            for call in by_message.get(i, [])
        ]
        if not message.text.strip() and not tool_calls:
            continue
        entry: HistoryEntry = {"i": i, "role": message.role, "text": message.text}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        entries.append(entry)
    return entries


def goal_from_messages(messages: Sequence[Message]) -> str:
    prompts = [
        m.text for m in messages if m.role == "user" and m.text.strip() and not m.tool_results
    ]
    return "\n".join(truncate(text, 500) for text in prompts[-3:])


def fit_state(
    messages: Sequence[Message], calls: Sequence[ToolCall], config: CompactionConfig
) -> FittedState:
    """Builds the Jev state and shrinks it in stages until it fits max_state_tokens.

    Raises JevCompactionError when even the last stage is too big.
    """
    goal = config.goal or goal_from_messages(messages)
    limit = config.max_state_tokens
    total = len(messages)

    def state_of(entries: list[HistoryEntry]) -> dict[str, Any]:
        return {"context": STATE_CONTEXT, "goal": goal, "history": entries}

    def entry_tokens(entry: HistoryEntry) -> int:
        return estimate_tokens(to_json(entry)) + 1

    def pinned(entry: HistoryEntry) -> bool:
        return is_pinned(entry["i"], total, config.preserve_recent_messages)

    base_tokens = estimate_tokens(to_json(state_of([])))
    history: list[HistoryEntry] = []
    per_entry: list[int] = []
    tokens = 0

    def rebuild(entries: list[HistoryEntry]) -> None:
        nonlocal history, per_entry, tokens
        history = entries
        per_entry = [entry_tokens(e) for e in history]
        tokens = base_tokens + sum(per_entry)

    def update(index: int, key: str, value: Any) -> None:
        nonlocal tokens
        history[index][key] = value
        now = entry_tokens(history[index])
        tokens += now - per_entry[index]
        per_entry[index] = now

    def fits() -> bool:
        return tokens <= limit

    rebuild(_history_entries(messages, calls, INPUT_CHARS[0]))
    if fits():
        return FittedState(state_of(history), tokens, "full")

    for chars in INPUT_CHARS[1:]:
        rebuild(_history_entries(messages, calls, chars))
        if fits():
            return FittedState(state_of(history), tokens, f"inputs<={chars}")

    order = [i for i, e in enumerate(history) if not pinned(e)] + [
        i for i, e in enumerate(history) if pinned(e)
    ]

    for index in order:
        text = history[index]["text"]
        if len(text) <= TEXT_HEAD + TEXT_TAIL + 40:
            continue
        update(index, "text", _abridge(text, TEXT_HEAD, TEXT_TAIL))
        if fits():
            return FittedState(state_of(history), tokens, "texts abridged")

    for index in order:
        entry = history[index]
        if pinned(entry) or not entry["text"]:
            continue
        update(index, "text", f"[… {len(messages[entry['i']].text)} chars omitted …]")
        if fits():
            return FittedState(state_of(history), tokens, "old messages collapsed")

    by_message = _calls_by_message(calls)
    for index in order:
        entry = history[index]
        own = by_message.get(entry["i"])
        if pinned(entry) or not own:
            continue
        update(index, "tool_calls", [_compact_call(call) for call in own])
        if fits():
            return FittedState(state_of(history), tokens, "old calls compacted")

    left: set[int] = set()
    for index in order:
        entry = history[index]
        if pinned(entry) or "tool_calls" in entry:
            continue
        left.add(index)
        tokens -= per_entry[index]
        if fits():
            remaining = [e for i, e in enumerate(history) if i not in left]
            return FittedState(state_of(remaining), tokens, "old messages left out")

    rebuild(_merge_call_runs([e for i, e in enumerate(history) if i not in left], pinned))
    if fits():
        return FittedState(state_of(history), tokens, "old calls merged")

    raise JevCompactionError(
        f"history too large for Jev (~{tokens} tokens after truncation, limit {limit})"
    )
