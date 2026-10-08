from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol

Role = Literal["user", "assistant"]
CallAction = Literal["keep", "drop_result", "drop_call"]
DecisionReason = Literal["pinned", "kept", "result_dropped", "call_dropped"]
# manual: the person asked (/compact); the others come from the policy's own thresholds.
TriggerLevel = Literal["soft", "hard", "idle", "manual"]
# skip: not triggered; apply: use the pruned transcript; defer: leave the transcript
# untouched; summarize: hand over to Claude Code's built-in compaction.
PolicyAction = Literal["skip", "apply", "defer", "summarize"]

JevQuestions = dict[str, dict[str, str]]


class JevCompactionError(Exception):
    pass


@dataclass(frozen=True)
class ToolUse:
    tool_use_id: str
    tool: str
    input: dict[str, Any]
    # Claude Code transcripts attach the outcome to the tool_use block too.
    text: str | None = None
    is_error: bool = False


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: Role
    text: str
    tool_uses: tuple[ToolUse, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class ToolCall:
    id: str
    tool_use_id: str
    tool: str
    input: dict[str, Any]
    call_index: int
    result_index: int
    result_chars: int
    is_error: bool
    pinned: bool


@dataclass(frozen=True)
class CallAnswer:
    keep_call: float
    keep_result: float


@dataclass(frozen=True)
class TextAnswer:
    keep_text: float


@dataclass(frozen=True)
class CallDecision:
    id: str
    tool: str
    keep_call: float
    keep_result: float
    action: CallAction
    reason: DecisionReason


@dataclass(frozen=True)
class FittedState:
    state: dict[str, Any]
    tokens: int
    stage: str


@dataclass(frozen=True)
class CompactStats:
    messages_before: int
    messages_after: int
    chars_before: int
    chars_after: int
    calls: int
    kept: int
    results_dropped: int
    calls_dropped: int
    pinned: int
    state_tokens: int
    state_stage: str
    requests: int
    reused: int
    ms: int


@dataclass(frozen=True)
class CompactResult:
    messages: list[Message]
    decisions: list[CallDecision]
    stats: CompactStats
    # Every non-pinned call's answer, keyed by tool_use_id, for reuse next round.
    answers: dict[str, CallAnswer]
    # For each output message, the index of the input message it came from.
    sources: list[int]


@dataclass(frozen=True)
class ContextUsage:
    used_tokens: int
    window_tokens: int
    # Time since the last turn ended; beyond the cache TTL the prompt cache is cold.
    idle_seconds: float = 0.0

    @property
    def percent(self) -> float:
        return 100 * self.used_tokens / self.window_tokens


@dataclass(frozen=True)
class CompactionMemory:
    """What one round leaves for the next; persisted by the caller."""

    # Context size right after the last apply or deferral; growth is measured from here.
    baseline_tokens: int | None = None
    answers: dict[str, CallAnswer] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyOutcome:
    action: PolicyAction
    level: TriggerLevel | None
    result: CompactResult | None
    freed_tokens: int
    percent_before: float
    percent_after: float
    memory: CompactionMemory
    # User-facing toast; empty when nothing was attempted.
    message: str


class JevAsker(Protocol):
    def ask(self, state: Mapping[str, Any], questions: JevQuestions) -> Mapping[str, Any]: ...
