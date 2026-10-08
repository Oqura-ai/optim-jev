from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Mapping, TypeVar

from .config import CompactionConfig
from .jev import JevClient, noul_answer
from .state import collect_tool_calls, estimate_tokens, fit_state, is_pinned, to_json
from .types import (
    CallAnswer,
    CallDecision,
    CompactResult,
    CompactStats,
    FittedState,
    JevAsker,
    JevCompactionError,
    JevQuestions,
    Message,
    ToolCall,
    ToolResult,
    ToolUse,
)

# Tokens the request envelope (model, key names) adds around state and questions.
REQUEST_OVERHEAD_TOKENS = 20
# Share of Jev's request budget one quoted assistant text may take.
TEXT_SHARE_OF_REQUEST = 0.6
# Assistant texts at or under this length are not worth judging.
MIN_TEXT_CHARS = 100


def questions_for(call: ToolCall) -> JevQuestions:
    return {
        f"call_{call.id}": {
            "type": "noul",
            "instructions": (
                f"Tool call {call.id} ({call.tool}) should stay in the history: knowing this call "
                "was made, with its input, still matters for what the assistant does next"
            ),
        },
        f"result_{call.id}": {
            "type": "noul",
            "instructions": (
                f"The full output of tool call {call.id} ({call.tool}, {call.result_chars} chars) "
                "should stay in the history verbatim: the assistant still needs its contents and "
                "re-running the tool would not do"
            ),
        },
    }


def _excerpt(text: str, max_tokens: int) -> str:
    tokens = estimate_tokens(text)
    if tokens <= max_tokens:
        return text
    keep = int(len(text) * max_tokens / tokens * 0.95)
    return f"{text[:keep]}\n[… {len(text) - keep} chars omitted …]"


def questions_for_text(msg_idx: int, text: str, max_text_tokens: int) -> JevQuestions:
    return {
        f"text_{msg_idx}": {
            "type": "noul",
            "instructions": (
                f"The assistant's text in message {msg_idx} ({len(text)} chars), quoted below, "
                "meaningfully contributes to understanding the coding logic, technical "
                "decisions, or problem-solving approach:\n\n"
                f"{_excerpt(text, max_text_tokens)}"
            ),
        },
    }


T = TypeVar("T")


def batch_items(
    items: Sequence[T],
    questions: Callable[[T], JevQuestions],
    state_tokens: int,
    max_request_tokens: int,
) -> list[list[T]]:
    """Splits items so that the state plus each batch's questions fits one request."""
    budget = max_request_tokens - state_tokens - REQUEST_OVERHEAD_TOKENS
    batches: list[list[T]] = []
    current: list[T] = []
    current_tokens = 0
    for item in items:
        tokens = estimate_tokens(to_json(questions(item)))
        if current and current_tokens + tokens > budget:
            batches.append(current)
            current, current_tokens = [], 0
        if not current and tokens > budget:
            raise JevCompactionError(
                f"state leaves no room for questions (~{state_tokens} of {max_request_tokens} tokens)"
            )
        current.append(item)
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


def batch_calls(
    calls: Sequence[ToolCall], state_tokens: int, max_request_tokens: int
) -> list[list[ToolCall]]:
    return batch_items(calls, questions_for, state_tokens, max_request_tokens)


def decide_call(call: ToolCall, answer: CallAnswer, keep_threshold: float) -> CallDecision:
    if call.pinned:
        action, reason = "keep", "pinned"
    elif answer.keep_result >= keep_threshold:
        action, reason = "keep", "kept"
    elif answer.keep_call >= keep_threshold:
        action, reason = "drop_result", "result_dropped"
    else:
        action, reason = "drop_call", "call_dropped"
    return CallDecision(call.id, call.tool, answer.keep_call, answer.keep_result, action, reason)


def _ask_text_batch(
    asker: JevAsker, state: Mapping[str, Any], batch: Sequence[tuple[int, str]], max_text_tokens: int
) -> dict[str, CallAnswer]:
    questions: JevQuestions = {}
    for idx, text in batch:
        questions.update(questions_for_text(idx, text, max_text_tokens))
    try:
        answers = asker.ask(state, questions)["answers"]
        return {f"text_{idx}": CallAnswer(noul_answer(answers, f"text_{idx}"), 1.0) for idx, _ in batch}
    except JevCompactionError:
        return {}  # a text left unjudged is kept; never fail the whole compaction over it


def _plan_texts(
    messages: Sequence[Message],
    calls: Sequence[ToolCall],
    config: CompactionConfig,
    fitted: FittedState,
    texts: Sequence[tuple[int, str]],
) -> tuple[Mapping[str, Any], list[list[tuple[int, str]]], int]:
    """State, batches and per-text cap for the text questions; no batches if nothing fits.

    A quoted text may take up to TEXT_SHARE_OF_REQUEST of the request. When the largest
    question doesn't fit beside the normal state, the state is refit smaller for these requests.
    """
    max_text_tokens = int(config.max_request_tokens * TEXT_SHARE_OF_REQUEST)
    largest = max(estimate_tokens(to_json(questions_for_text(i, t, max_text_tokens))) for i, t in texts)
    state_budget = config.max_request_tokens - largest - REQUEST_OVERHEAD_TOKENS
    state = fitted
    if fitted.tokens > state_budget:
        try:
            state = fit_state(messages, calls, replace(config, max_state_tokens=max(1, state_budget)))
        except JevCompactionError:
            return {}, [], max_text_tokens
    def questions(item: tuple[int, str]) -> JevQuestions:
        return questions_for_text(item[0], item[1], max_text_tokens)

    try:
        batches = batch_items(texts, questions, state.tokens, config.max_request_tokens)
    except JevCompactionError:
        return {}, [], max_text_tokens
    return state.state, batches, max_text_tokens


def _ask_batch(
    asker: JevAsker, state: Mapping[str, Any], batch: Sequence[ToolCall]
) -> dict[str, CallAnswer]:
    questions: JevQuestions = {}
    for call in batch:
        questions.update(questions_for(call))
    answers = asker.ask(state, questions)["answers"]
    return {
        call.id: CallAnswer(
            keep_call=noul_answer(answers, f"call_{call.id}"),
            keep_result=noul_answer(answers, f"result_{call.id}"),
        )
        for call in batch
    }


def _truncated_text(text: str, is_error: bool, head_chars: int) -> str:
    if len(text) <= head_chars + 120:
        return text
    head = f"{text[:head_chars]}\n" if head_chars > 0 else ""
    error = " (error)" if is_error else ""
    return (
        f"{head}[jev-compacter truncated {len(text) - head_chars} chars of this tool result{error}; "
        "re-run the tool if needed]"
    )


def _same(a: Sequence[object], b: Sequence[object]) -> bool:
    return len(a) == len(b) and all(x is y for x, y in zip(a, b))


def apply_decisions(
    messages: Sequence[Message],
    decisions: Sequence[CallDecision],
    calls: Sequence[ToolCall],
    head_chars: int,
    prune_texts: Collection[str] = (),
) -> list[Message]:
    """Rebuilds the transcript; a dropped call goes with its result, untouched messages are reused.

    prune_texts: keys f"text_{index}" of assistant texts to cut down to their head.
    """
    return [message for _, message in _rebuild(messages, decisions, calls, head_chars, prune_texts)]


def _pruned_text(text: str, head_chars: int) -> str:
    if len(text) <= head_chars + 120:
        return text
    return f"{text[:head_chars]}\n[jev-compacter truncated {len(text) - head_chars} chars of this message]"


def _rebuild(
    messages: Sequence[Message],
    decisions: Sequence[CallDecision],
    calls: Sequence[ToolCall],
    head_chars: int,
    prune_texts: Collection[str] = (),
) -> list[tuple[int, Message]]:
    by_id = {call.id: call for call in calls}
    actions = {
        by_id[d.id].tool_use_id: d.action for d in decisions if d.id in by_id and d.action != "keep"
    }

    def use(tool: ToolUse) -> ToolUse:
        if actions.get(tool.tool_use_id) != "drop_result":
            return tool
        text = _truncated_text(tool.text or "", tool.is_error, head_chars)
        return tool if text == (tool.text or "") else replace(tool, text=text)

    def result(item: ToolResult) -> ToolResult:
        if actions.get(item.tool_use_id) != "drop_result":
            return item
        text = _truncated_text(item.text, item.is_error, head_chars)
        return item if text == item.text else replace(item, text=text)

    kept: list[tuple[int, Message]] = []
    for index, message in enumerate(messages):
        tool_uses = tuple(
            use(t) for t in message.tool_uses if actions.get(t.tool_use_id) != "drop_call"
        )
        tool_results = tuple(
            result(r) for r in message.tool_results if actions.get(r.tool_use_id) != "drop_call"
        )

        text = _pruned_text(message.text, head_chars) if f"text_{index}" in prune_texts else message.text

        if _same(tool_uses, message.tool_uses) and _same(tool_results, message.tool_results) and text == message.text:
            kept.append((index, message))
        elif text.strip() or tool_uses or tool_results:
            kept.append((index, replace(message, text=text, tool_uses=tool_uses, tool_results=tool_results)))
    return kept


def message_tokens(message: Message) -> int:
    """Estimated tokens the message costs in context (tool_use.text only mirrors the result)."""
    total = estimate_tokens(message.text)
    for tool in message.tool_uses:
        try:
            total += estimate_tokens(to_json(tool.input))
        except (TypeError, ValueError):
            total += 20
    return total + sum(estimate_tokens(r.text) for r in message.tool_results)


def message_chars(message: Message) -> int:
    total = len(message.text)
    for tool in message.tool_uses:
        try:
            total += len(to_json(tool.input))
        except (TypeError, ValueError):
            total += 20
    return total + sum(len(r.text) for r in message.tool_results)


def reduction_ratio(result: CompactResult) -> float:
    before, after = result.stats.chars_before, result.stats.chars_after
    return 0.0 if before == 0 else (before - after) / before


def _borderline(answer: CallAnswer, config: CompactionConfig) -> bool:
    t, m = config.keep_threshold, config.reask_margin
    return abs(answer.keep_call - t) < m or abs(answer.keep_result - t) < m


def compact(
    messages: Sequence[Message],
    asker: JevAsker,
    config: CompactionConfig = CompactionConfig(),
    known: Mapping[str, CallAnswer] | None = None,
) -> CompactResult:
    """Drops tool calls/results and explanatory text Jev says are no longer needed; raises JevCompactionError on failure.

    `known` holds answers from earlier rounds by tool_use_id or text_<index>; only new or borderline items are asked.
    """
    started = time.monotonic()
    known = known or {}
    calls = collect_tool_calls(messages, config.preserve_recent_messages)
    candidates = [call for call in calls if not call.pinned]
    to_ask = [
        call
        for call in candidates
        if call.tool_use_id not in known or _borderline(known[call.tool_use_id], config)
    ]

    state_tokens, state_stage = 0, ""
    batches: list[list[ToolCall]] = []
    asked: dict[str, CallAnswer] = {}

    text_batches: list[list[tuple[int, str]]] = []
    text_candidates = [
        (idx, msg.text)
        for idx, msg in enumerate(messages)
        if msg.role == "assistant"
        and len(msg.text) > MIN_TEXT_CHARS
        and not is_pinned(idx, len(messages), config.preserve_recent_messages)
    ]
    texts_to_ask = [
        (idx, text)
        for idx, text in text_candidates
        if f"text_{idx}" not in known or _borderline(known[f"text_{idx}"], config)
    ]

    if to_ask or texts_to_ask:
        fitted = fit_state(messages, calls, config)
        state_tokens, state_stage = fitted.tokens, fitted.stage

        if to_ask:
            batches = batch_calls(to_ask, fitted.tokens, config.max_request_tokens)
            with ThreadPoolExecutor(max_workers=len(batches)) as pool:
                for batch_answers in pool.map(lambda b: _ask_batch(asker, fitted.state, b), batches):
                    asked.update(batch_answers)

        if texts_to_ask:
            text_state, text_batches, max_text_tokens = _plan_texts(messages, calls, config, fitted, texts_to_ask)
            if text_batches:
                with ThreadPoolExecutor(max_workers=len(text_batches)) as pool:
                    for batch_answers in pool.map(
                        lambda b: _ask_text_batch(asker, text_state, b, max_text_tokens), text_batches
                    ):
                        asked.update(batch_answers)

    def answer_for(call: ToolCall) -> CallAnswer:
        if call.id in asked:
            return asked[call.id]
        return known.get(call.tool_use_id, CallAnswer(1.0, 1.0))

    decisions = [decide_call(call, answer_for(call), config.keep_threshold) for call in calls]

    text_answers: dict[str, CallAnswer] = {}
    for idx, _ in text_candidates:
        key = f"text_{idx}"
        answer = asked.get(key) or known.get(key)
        if answer is not None:
            text_answers[key] = answer
    prune_texts = {key for key, a in text_answers.items() if a.keep_call < config.keep_threshold}

    rebuilt = _rebuild(messages, decisions, calls, config.truncate_head_chars, prune_texts)
    kept = [message for _, message in rebuilt]
    reasons = [d.reason for d in decisions]

    all_answers = {call.tool_use_id: answer_for(call) for call in candidates}
    all_answers.update(text_answers)

    return CompactResult(
        messages=kept,
        decisions=decisions,
        stats=CompactStats(
            messages_before=len(messages),
            messages_after=len(kept),
            chars_before=sum(message_chars(m) for m in messages),
            chars_after=sum(message_chars(m) for m in kept),
            calls=len(calls),
            kept=reasons.count("kept"),
            results_dropped=reasons.count("result_dropped"),
            calls_dropped=reasons.count("call_dropped"),
            pinned=reasons.count("pinned"),
            state_tokens=state_tokens,
            state_stage=state_stage,
            requests=len(batches) + len(text_batches),
            reused=len(candidates) - len(to_ask),
            ms=round((time.monotonic() - started) * 1000),
        ),
        answers=all_answers,
        sources=[index for index, _ in rebuilt],
    )


def compact_messages(
    messages: Sequence[Message],
    config: CompactionConfig = CompactionConfig(),
    api_key: str | None = None,
) -> CompactResult:
    """compact() over HTTP; the key defaults to TYPESAFE_API_KEY."""
    return compact(messages, JevClient(api_key, config.model, config.base_url), config)
