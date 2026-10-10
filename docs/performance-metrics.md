# Performance metrics

Each tool has a `stats` command that compares what it cost against what would have happened without it, in US dollars, for the **current session only**:

| Command | Compares |
|---|---|
| `/jev-compact stats` | Jev pruning vs Claude Code's built-in summary |
| `/jev-route stats` | Routed subagents vs the same work priced at the main model |
| `/jev-skills stats` | Jev's shortlist vs the built-in list of every skill |

Each report has the same shape: an **Activity** table, a **Cost** table whose last row is the net result, then notes ending with the prices used. Every cost row's **Basis** column says whether it is **measured** (real token counts from the logs) or **est.** (estimated).

## Where the numbers come from

All inputs are the per-session logs in `.optim-jev/logs/` (see [Architecture](architecture.md#session-logs)):

| Log | Holds |
|---|---|
| `claude/<session>.jsonl` | Claude's own token usage per turn, per built-in summary, per routed subagent |
| `jev_compacter/<session>.jsonl` | One record per compaction, with Jev's usage |
| `jev_router/<session>.jsonl` | One record per routed subagent and per turn outcome, with Jev's usage |
| `jev_skills/<session>.jsonl` | One record per shortlist and per skill loaded, with Jev's usage |

## Prices

Defined in [`src/optim_jev/core/pricing.py`](../src/optim_jev/core/pricing.py). Edit them there if yours differ.

| Model | Input / 1M | Output / 1M |
|---|---|---|
| opus | $5.00 | $25.00 |
| sonnet | $3.00 | $15.00 |
| haiku | $1.00 | $5.00 |
| Jev | $0.04 | $0.00 |

The model is matched by family name inside the model id, so `claude-haiku-5-5` is priced as haiku. Cached input is priced from the input rate:

- **cache read**: 0.1 × input
- **cache write**: 1.25 × input

A Claude usage record is priced as:

```
input × in  +  cache_read × in × 0.1  +  cache_write × in × 1.25  +  output × out
```

Jev's cost is logged with each record at the price in force at the time, so changing Jev's price later doesn't rewrite old sessions.

## `/jev-compact stats`

![jev-compacter](../assets/jev-compacter.png)

**Measured:** number of compactions by outcome, Jev's tokens and cost, and the real cost of every built-in summary that ran.

**Compared:** for each compaction where Jev's prune was applied, what a built-in summary in its place would have cost.

| Line | How it's worked out |
|---|---|
| Built-in summary (est.) | the context priced as a cache read (it's already cached when the summary runs) + output tokens = context × *output ratio*, at the main model's prices |
| Jev pruning (measured) | Jev's logged cost for that compaction |
| Larger context re-read (est.) | Jev leaves more context than a summary does: (context Jev left − context a summary would leave) × cache-read price × main-loop turns until the next compaction |
| Net saved / Net extra cost | summary − Jev − re-read |

The *output ratio* and the share of context a summary keeps are **measured from this session's own built-in summaries** when any ran. Until then they default to 10% each, and the report says so.

Also shown: Jev spend on rounds that still fell back to the summary, since that money bought nothing.

## `/jev-route stats`

![jev-router](../assets/jev-router.png)

**Measured:** every turn of every routed subagent, priced at the model it actually ran on, plus Jev's routing cost.

**Compared:** the same tokens priced at the main loop's model, i.e. "what if the main model had done this work itself".

| Line | How it's worked out |
|---|---|
| Subagents on routed models (measured) | each subagent turn priced at its own model |
| Same work on the main model (est.) | the same turns priced at the main loop's latest model |
| Jev routing (measured) | Jev's logged cost |
| Net saved / Net extra cost | main-model price − routed price − Jev |

What the estimate leaves out: had the main loop done the work, its own context would have grown, making every later turn dearer. So the real saving is usually **larger** than reported.

If the main model and the routed model are the same, the saving is $0, which is correct.

## `/jev-skills stats`

![jev-skills](../assets/jev-skills.png)

**Compared:** Claude Code's built-in skill list, which goes out with every request, against Jev's per-prompt shortlist.

| Line | How it's worked out |
|---|---|
| Built-in skill list (est.) | listing size × input price × (one cache write + one cache read per later main-loop turn) |
| Shortlist notes (est.) | size of all shortlist notes × input price × cache write |
| Jev (measured) | Jev's logged cost |
| Net saved / Net extra cost | listing − notes − Jev |

The listing isn't logged, so its size is estimated from the skill index at about 4 characters per token. Note sizes are estimated the same way. Later turns re-reading old notes from the cache are left out.

## Reading the result

- **net saved**: the tool cost less than the alternative.
- **net extra**: it cost more. Common reasons: the main model and routed model are the same (router), very few skills in scope (skills), or a prune that freed little but left a large context to re-read (compacter).
- Small sessions give small, noisy numbers. Compare across a few sessions before drawing conclusions.
