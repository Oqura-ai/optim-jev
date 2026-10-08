# jev-compacter

![jev-compacter](../assets/jev-compacter.png)

Replaces Claude Code's built-in compaction summary with a prune: Jev judges each tool call in the conversation, and stale ones are dropped or cut short. Everything else stays word for word.

## When it runs

| Trigger | Level |
|---|---|
| you type `/compact` | `manual` |
| Claude Code auto-compacts near its limit | `hard` |
| a turn ends with the context ≥ 60% full and grown ≥ 10% since the last compaction | `soft` (≥ 85% gives `hard`) |
| a subagent compacts, or a precompute | skipped: built-in behaviour |

The level decides the fallback when the prune doesn't help enough.

## One compaction, step by step

1. **Pair calls with results.** Calls in the first message and in the newest 6 messages are **pinned**: never sent to Jev, never touched.
2. **Reuse what's known.** Jev's scores from earlier compactions in this session are reused unless they were close to the threshold.
3. **Build what Jev sees.** The whole conversation with every tool output replaced by a size note. If it's over 25k tokens it is shrunk in stages (shorter inputs, head-and-tail texts, collapsed old messages).
4. **Ask Jev.** Two questions per call, batched and run in parallel: should the *call* stay, and should its *full output* stay?
5. **Decide each call** (threshold 0.5):
   - output should stay → **keep**
   - only the call should stay → **truncate**: first 300 characters of the output plus a note to re-run the tool
   - neither → **drop** the call and its output
6. **Judge the result:**

| Level | Applied if | Otherwise |
|---|---|---|
| `hard` | the context lands below 60% | built-in summary |
| `manual` | it frees something, and lands at ≤ 40%, or frees ≥ 8000 tokens | built-in summary |
| `soft` | same as manual | deferred to a later turn, scores kept |
| Jev fails | — | summary for hard/manual, defer for soft |

7. **Hand back.** Kept messages are returned as indexes into the original list, so unchanged messages are reused exactly as Claude Code had them.

## Memory

Jev's scores per tool call are kept in the session's log file, tagged with a fingerprint of the tool and its input. A remembered score is reused only if that call is still in the conversation with the same input, so rewinds and edits never reuse stale answers. The file is removed when the session's transcript is gone.

## Files

| File | Role |
|---|---|
| [`tool.py`](../src/optim_jev/tools/jev_compacter/tool.py) | entry point: modes `check`, `compact`, `stats` |
| [`policy.py`](../src/optim_jev/tools/jev_compacter/policy.py) | *when* to compact, and *whether* to apply the result |
| [`logic.py`](../src/optim_jev/tools/jev_compacter/logic.py) | asks Jev, decides per call, rebuilds the messages |
| [`state.py`](../src/optim_jev/tools/jev_compacter/state.py) | what Jev sees, shrunk to fit |
| [`jev.py`](../src/optim_jev/tools/jev_compacter/jev.py) | HTTP client for Jev, shared by all tools; counts usage |
| [`store.py`](../src/optim_jev/tools/jev_compacter/store.py) | memory and outcome records in the session log |
| [`stats.py`](../src/optim_jev/tools/jev_compacter/stats.py) | `/jev-compact stats` |
| [`config.py`](../src/optim_jev/tools/jev_compacter/config.py) | defaults |
| [`types.py`](../src/optim_jev/tools/jev_compacter/types.py) | frozen dataclasses |

## Settings

Defaults are in [`config.py`](../src/optim_jev/tools/jev_compacter/config.py). The ones exposed in `/config` are listed in [Getting started](getting-started.md#options). Others are read from options too but not declared in the manifest: `max_state_tokens` (25000), `max_request_tokens` (30000), `truncate_head_chars` (300), `reask_margin` (0.15), `regrow_percent` (10), `model`, `base_url`.

## Known gaps

- Only tool calls and their outputs are judged; Claude's own text replies are never pruned.
- Tokens freed are estimated without a tokenizer.
- Text after `/compact` is only used if the built-in summary runs.
