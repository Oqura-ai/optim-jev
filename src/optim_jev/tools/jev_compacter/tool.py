"""Claude Code bridge: hooks/optim-jev.ts sends one JSON request on stdin, gets one JSON answer.

    python -m optim_jev.tools.jev_compacter.tool check    -> {"level": "soft" | "hard" | null}
    python -m optim_jev.tools.jev_compacter.tool compact
        -> {"action", "message", "log", "freedTokensEst", "messages"?}

Request fields: session_id, project_dir, usage {used_tokens, window_tokens, idle_seconds}, options
(the plugin's userConfig; this tool reads the `jev_compacter_` keys), and for `compact` the
engine's messages plus the forced `level`. In the answer each kept message is `{"from": i}`
(the engine's own message i, unchanged) or `{"from": i, "toolUses", "toolResults"}` (message i
keeping only the listed blocks, with the given texts).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import asdict
from typing import Any

from . import stats as stats_mod, store
from ...core import pricing
from .config import CompactionConfig
from .jev import JevClient
from .policy import plan_compaction, trigger_level
from .types import CompactionMemory, ContextUsage, Message, PolicyOutcome, ToolResult, ToolUse

OPTION_PREFIX = "jev_compacter_"
_LOG_LINE_CHARS = 3500


def _config(options: Any) -> CompactionConfig:
    raw = options if isinstance(options, dict) else {}
    return CompactionConfig.from_mapping(
        {k[len(OPTION_PREFIX):]: v for k, v in raw.items() if k.startswith(OPTION_PREFIX)}
    )


def _usage(raw: dict[str, Any]) -> ContextUsage:
    return ContextUsage(
        used_tokens=int(raw.get("used_tokens") or 0),
        window_tokens=max(1, int(raw.get("window_tokens") or 1)),
        idle_seconds=float(raw.get("idle_seconds") or 0),
    )


def _message(raw: dict[str, Any]) -> Message:
    return Message(
        role=raw["role"],
        text=raw.get("text") or "",
        tool_uses=tuple(
            ToolUse(t["tool_use_id"], t["tool"], t.get("input") or {}, t.get("text"), bool(t.get("isError")))
            for t in raw.get("toolUses") or ()
        ),
        tool_results=tuple(
            ToolResult(r["tool_use_id"], r.get("text") or "", bool(r.get("isError")))
            for r in raw.get("toolResults") or ()
        ),
    )


def locate_transcript(session_id: str) -> str | None:
    """The session's .jsonl under Claude Code's config dir, whatever its project folder is named."""
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    pattern = os.path.join(glob.escape(config_dir), "projects", "*", f"{glob.escape(session_id)}.jsonl")
    matches = glob.glob(pattern)
    return matches[0] if matches else None


def _wire(source: int, original: Message, kept: Message) -> dict[str, Any]:
    if kept is original:
        return {"from": source}
    return {
        "from": source,
        "toolUses": [
            {"tool_use_id": t.tool_use_id, **({} if t.text is None else {"text": t.text})}
            for t in kept.tool_uses
        ],
        "toolResults": [{"tool_use_id": r.tool_use_id, "text": r.text} for r in kept.tool_results],
    }


def _log(outcome: PolicyOutcome) -> list[str]:
    result = outcome.result
    if result is None:
        return []
    s = result.stats
    lines = [
        f"jev-compacter: {outcome.action} ({outcome.level}); calls={s.calls} kept={s.kept} "
        f"truncated={s.results_dropped} dropped={s.calls_dropped} pinned={s.pinned} reused={s.reused} "
        f"state~{s.state_tokens} ({s.state_stage or 'none'}) requests={s.requests} {s.ms}ms"
    ]
    entries = [
        f"{d.id}:{d.tool}:{d.action}/call={d.keep_call:.2f}/result={d.keep_result:.2f}"
        for d in result.decisions
        if d.reason != "pinned"
    ]
    line = "decisions:"
    for entry in entries:
        if len(line) + len(entry) + 1 > _LOG_LINE_CHARS:
            lines.append(line)
            line = "decisions:"
        line = f"{line} {entry}"
    if entries:
        lines.append(line)
    return lines


def _outcome_record(outcome: PolicyOutcome, usage: ContextUsage, message_count: int, jev: JevClient) -> dict[str, Any]:
    """Raw numbers of one compaction; token figures other than `used_tokens` and Jev's are estimates."""
    result = outcome.result
    return {
        "kind": "compaction",
        "action": outcome.action,
        "level": outcome.level,
        "used_tokens": usage.used_tokens,
        "window_tokens": usage.window_tokens,
        "messages_before": message_count,
        "messages_after": len(result.messages) if result else message_count,
        "freed_tokens_est": outcome.freed_tokens,
        "percent_before": round(outcome.percent_before, 2),
        "percent_after_est": round(outcome.percent_after, 2),
        "stats": asdict(result.stats) if result else None,
        "jev": jev.usage(),
    }


def check(request: dict[str, Any]) -> dict[str, Any]:
    config = _config(request.get("options"))
    session_id = request["session_id"]
    transcript = locate_transcript(session_id)
    memory = CompactionMemory()
    if transcript:
        memory = store.load(store.store_dir(request["project_dir"]), session_id, transcript, [])
    return {"level": trigger_level(_usage(request["usage"]), memory, config)}


def compact(request: dict[str, Any]) -> dict[str, Any]:
    config = _config(request.get("options"))
    session_id = request["session_id"]
    messages = [_message(m) for m in request["messages"]]
    usage = _usage(request["usage"])
    directory = store.store_dir(request["project_dir"])
    transcript = locate_transcript(session_id)

    memory = CompactionMemory()
    if transcript:
        store.sweep(directory)
        memory = store.load(directory, session_id, transcript, messages)

    jev = JevClient(model=config.model, base_url=config.base_url)
    outcome = plan_compaction(messages, usage, jev, memory, config, level=request.get("level"))

    if transcript:
        if outcome.action == "summarize":
            # The summary replaces the transcript: an empty snapshot, keeping the outcomes logged so far.
            store.save(directory, session_id, transcript, [], CompactionMemory())
        elif outcome.action == "apply" and outcome.result is not None:
            store.save(directory, session_id, transcript, outcome.result.messages, outcome.memory)
        elif outcome.action == "defer":
            store.save(directory, session_id, transcript, messages, outcome.memory)
    if outcome.action != "skip":
        store.log_outcome(directory, session_id, _outcome_record(outcome, usage, len(messages), jev))

    answer: dict[str, Any] = {
        "action": outcome.action,
        "message": outcome.message,
        "log": _log(outcome),
        "freedTokensEst": outcome.freed_tokens,
    }
    if outcome.action == "apply" and outcome.result is not None:
        answer["messages"] = [
            _wire(source, messages[source], kept)
            for source, kept in zip(outcome.result.sources, outcome.result.messages)
        ]
        answer["tokensAfter"] = max(0, usage.used_tokens - outcome.freed_tokens)
    return answer


def stats(request: dict[str, Any]) -> dict[str, Any]:
    session_id = request["session_id"]
    records = store.read_all(store.store_dir(request["project_dir"]), session_id)
    compactions = [r for r in records if r.get("kind") == "compaction"]
    return {"text": stats_mod.report(compactions, pricing.claude_log(request["project_dir"], session_id))}


def main() -> None:
    handlers = {"check": check, "compact": compact, "stats": stats}
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in handlers:
        sys.exit(f"usage: python -m optim_jev.tools.jev_compacter.tool {{{'|'.join(handlers)}}}")
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.buffer.write(json.dumps(handlers[mode](request), ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
