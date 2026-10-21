# Feedback on the experiment design

The structure is good: a linear baseline, the routing approach other tools use, plain sub-agents, then the target. Including tasks where sub-agents are expected to lose makes the results more credible. I'd make five changes before building it.

## 1. Write each task once and derive both traces from it

"Same task, linear vs tree" is only fair if both traces come from one source. I'd write each task as a **tree** (main loop plus sub-agent segments) and produce the linear trace automatically by flattening it:
- each sub-agent's requests are inlined into the main loop,
- the hand-off requests (writing the task prompt, reading the result back) are removed,
- the duplicate file reads are removed.

The work content stays identical in both shapes, so any difference comes from structure, prices and caching, not from how we happened to write the traces. It also leaves one source per task to maintain, not two.

## 2. Read delegation belongs in the tree, not just the target

You said the target uses the same trace as Opus sub-agent mode. Then delegated reads (explain, investigate) must already be sub-agent branches in that tree, so arm 3 runs them as fresh Opus sub-agents too. Otherwise the target's trace differs from arm 3's and the comparison breaks.

With that, the target differs from arm 3 in exactly two ways:
- **routed models** (Sonnet and Haiku where the labels allow),
- **sub-agents kept alive** (reused while their cache is warm).

Since two things change at once, I'd add two small attribution arms in an appendix, not in the headline:
- target with routing but fresh sub-agents,
- target with live sub-agents, all on Opus.

That answers "how much does keeping sub-agents alive add on its own?" before anyone asks.

## 3. Make the per-turn routing arm a fair opponent

If arm 2 looks set up to lose, the comparison loses credibility. Give it the best version of itself:
- it switches models using the **ground-truth labels** (never picks wrong),
- it **switches only at task boundaries**, not mid-task,
- it pays the real cost of each switch: the whole context rewritten on the new model.

If it still loses, or only wins on a narrow band, that's a convincing case for sub-agents. If it wins in some task, we report that.

## 4. Model compaction explicitly

Both linear arms (1 and 2) need it for the long task. Simulated rules:
- **Trigger:** the main context reaches the auto-compact threshold for a configurable window size. Use about 200K tokens as the working window rather than Opus 5.5's 1M, otherwise the long task would have to be enormous to trigger it. Say so in the write-up.
- **Cost of a compaction:** one summary request, which re-reads the whole context from cache and outputs a summary (default 10% of the context, as the compacter's stats already assume), then a fresh cache write of the summary-only context.
- **After:** the main context restarts at the summary size.

Report the number of compactions per arm and the context-over-time chart. For the honesty section: the simulation counts what compaction *costs*, not what it *loses*. Loss of memory after compaction is the qualitative claim, and only the later live recall test can support it.

The tree arms (3 and target) may also compact on the long task, just later. The same rules apply to them, and to long-lived sub-agents whose own context grows past the cap.

## 5. Three tasks, chosen so each arm can win or lose

| Task | Shape | Who should win |
|---|---|---|
| **T1: long feature session** (~150–300 requests: investigate, plan, implement across modules, tests, docs, follow-ups) | forces at least one compaction in the linear arms | tree arms, especially the target |
| **T2: tight debug loop** (one bug: read, edit, run test, inspect, edit again, ~6–10 iterations on the same 1–2 files) | every iteration needs the previous result; hand-offs and re-reads repeat | linear Opus; sub-agents expected to lose |
| **T3: many tiny edits** (rename, fix a typo, change a constant, one-line doc changes, ~15 tasks of a few hundred tokens each) | fixed per-sub-agent overhead is larger than the work | linear Opus, or close; tests where delegation stops paying |

T2 and T3 are the "sub-agents may fail" cases you asked for. Live sub-agents in the target should narrow the gap on T2, because the same debugging sub-agent keeps its context. That's an honest, interesting result either way.

All three are built on **demo/tinycart**, so `policy.pick()` sees real paths later if we add a Jev-routed arm.

## Final arm list

| # | Arm | Trace | Models | Sub-agents |
|---|---|---|---|---|
| B1 | Opus, normal mode | linear (flattened) | Opus | none; compacts when full |
| B2 | Opus with per-turn model routing | linear (flattened) | switches by label at task boundaries | none; compacts when full |
| B3 | Opus sub-agent mode | tree | Opus everywhere | fresh per task, reads and writes |
| T | jev-router target | tree | Opus planner, routed sub-agents | kept alive (warm, under a context cap), reads and writes |
| appendix | T with fresh sub-agents; T with live sub-agents all on Opus | tree | as named | attribution only |

**Headline charts:**
1. main-loop context over time for each task, with compaction points marked,
2. total cost per arm per task, split by component.

**Second tier:** compactions per arm, hand-off overhead, how often live sub-agents were reused and how often their cache was still warm.

## Parameters to fix up front

These decide the results, so they should be agreed before running anything:
- **TTL and idle gaps** in the traces. Live sub-agents depend completely on whether gaps are under 5 minutes. I'd put realistic gaps in the trace timestamps (thinking pauses, user pauses) instead of assuming none.
- **Live sub-agent reuse rule:** same tier, overlapping files, last request under 4 minutes ago, context under 40K tokens.
- **Hand-off sizes:** task prompt and result, by task type.
- **Window size and compaction threshold.**
- **Price table:** the current table, since the experiment comes before the pricing PR.

## Limitations to state in the write-up

- **Quality is held equal.** Every arm completes every task with the same work; no failures or escalations.
- **The traces are written by us**, with token sizes partly estimated.
- **Compaction's loss of context isn't measured.**
- **Live-sub-agent results are sensitive to the timing assumptions** (gaps and TTL).

Next step: if this works for you, I'll draft the trace schema and the T1/T2/T3 outlines (labelled segments with token sizes) for review before any simulator code.