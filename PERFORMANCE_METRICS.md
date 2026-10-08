# Performance Metrics Guide

This guide explains how optim-jev calculates and reports the cost of each tool's optimizations. Each comparison measures real token counts from your session logs against estimated alternatives.

## Token Pricing Model

All costs are calculated using Claude's published pricing plus cache multipliers:

| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| **Opus** | $5.00/1M | $25.00/1M | 0.1× input | 1.25× input |
| **Sonnet** | $3.00/1M | $15.00/1M | 0.1× input | 1.25× input |
| **Haiku** | $1.00/1M | $5.00/1M | 0.1× input | 1.25× input |
| **Jev** | $0.04/1M | $0.00/1M | — | — |

**Cache read** (0.1×): When the prompt cache already holds your conversation, Claude re-reads it at 10% of the input price.

**Cache write** (1.25×): When Claude writes a new cache entry, the write costs 25% more than input tokens.

Edit [`core/pricing.py`](src/optim_jev/core/pricing.py) to update these if your pricing differs.

---

## `/jev-compact stats` — Compaction Performance

Reports whether Jev's pruning saves money compared to Claude Code's built-in summary.

### What's Measured
- **Real token counts** from your compaction and summary logs
- **Jev API cost** ($0.04 per million input tokens; output is free)
- **Summary costs** from actual summaries your session ran

### What's Estimated
- **Summary output tokens**: If no summary ran yet, assumes 10% of the context size
- **Summary context after**: If no summary ran yet, assumes 10% of the original (learned from actual summaries when available)
- **Cost of re-reading context after**: Assumes every turn re-reads the context left by the compaction from the cache

### The Calculation

For each **applied** Jev prune:

```
Summary Alternative Cost =
  (context_before tokens × input_price × cache_write)           [write to cache once]
  + (summary_output tokens × output_price × 1.25)               [write the summary]

Jev Prune Cost = 
  (jev_input_tokens × $0.04)

Extra Cost of Larger Context =
  (tokens_jev_left × input_price × cache_read) × turns_after    [re-read each turn]
  - (tokens_summary_left × input_price × cache_read) × turns_after

Net Savings = Summary Cost - Jev Cost - Extra Context Cost
```

**Example**: You run a compaction on a 100k-token context with Haiku as your session model.
- Summary would cost: 100k × $1 × 1.25 (write) + 6.6k × $5 (output at 6.6%) ≈ $0.16
- Jev cost: $0.0005 (from the log)
- Jev keeps 40% → 40k tokens; summary keeps 10% → 10k tokens
- If 5 more turns follow: re-read cost = (40k - 10k) × $1 × 0.1 × 5 ≈ $0.15
- **Net saved: $0.16 - $0.0005 - $0.15 = $0.0095**

### Why This Works
- Jev pruning leaves *more* context than the built-in summary (Jev keeps semantic tokens; summaries compress)
- But Jev is cheap ($0.04/1M), while re-reading a larger context from cache adds up
- The trade-off: spend less now on Jev, pay a bit more later in re-reads, net out cheaper

### When to Trust This
- ✅ Jev cost is **measured** (from the API log)
- ✅ Summary cost and size are **measured** once this session runs a summary
- ⚠️ Before that, uses 10% assumptions — valid but approximate
- ⚠️ Re-read cost is **estimated** (assumes cache hits on every turn; real behavior depends on your cache TTL)

---

## `/jev-route stats` — Subagent Routing Performance

Reports whether routing subagents to cheaper models saves money compared to having the main loop do the work.

### What's Measured
- **Real token counts** from each subagent's turns (logged in `claude/<session_id>.jsonl`)
- **Actual model used** (the session's model when subagent runs)
- **Jev routing cost** ($0.04 per million input tokens for each route decision)

### What's Estimated
- **Cost on the main model**: Same token counts, priced at the main loop's model (e.g., if main is Opus, estimates how much those subagent tokens would cost on Opus)
- **Main loop's own cost**: Measures the main loop's actual turns, but leaves out how much its *context* would have grown

### The Calculation

```
Actual Subagent Cost = 
  SUM over each subagent turn:
    (input_tokens × model_input_price)
    + (cache_read_tokens × model_input_price × 0.1)
    + (cache_write_tokens × model_input_price × 1.25)
    + (output_tokens × model_output_price)

Estimated Same-On-Main-Model =
  Same calculation, but using main_model's prices

Jev Routing Cost =
  SUM of (requests × $0.04/1M + output tokens × $0) from router logs

Net Savings = Estimated Main Cost - Actual Subagent Cost - Jev Routing Cost
```

**Example**: Your main loop is Sonnet ($3/$15). You route 100k tokens to a Haiku subagent.
- Actual subagent cost: 100k × $1 input (Haiku) ≈ $0.10
- If the main loop did it: 100k × $3 input (Sonnet) ≈ $0.30
- Jev routing: 1 decision × $0.04/1M ≈ $0.00004
- **Net saved: $0.30 - $0.10 - $0.00004 ≈ $0.20**

### Why This Works
- Cheap models (Haiku) handle many tasks as well as expensive ones (Sonnet, Opus)
- Routing costs almost nothing ($0.04/1M input)
- The main loop doesn't spawn subagents for free: it has to generate a task description and read the subagent's report

### When to Trust This
- ✅ Subagent token counts are **measured** (from the actual turns)
- ✅ Jev routing cost is **measured** (from the router logs)
- ⚠️ Main model cost is **estimated** (assumes the same tokens would be sent; doesn't account for expanded context, different approach, or re-runs)
- ⚠️ Leaves out the main loop's cache cost growth (every subagent spawn increases the main loop's context size)

---

## `/jev-skills stats` — Skill Picker Performance

Reports whether Jev's shortlisting saves money compared to sending the built-in skill listing with every request.

### What's Measured
- **Real skill roster size** (from your project's skill index)
- **Jev shortlist cost** ($0.04 per million input tokens for each ranking call)
- **Main loop turns** (from the Claude usage log)

### What's Estimated
- **Built-in listing size**: Counts from the skill index at ~4 characters per token
- **Shortlist note size**: Estimated from picked skill names and descriptions
- **Cache behavior**: Assumes the listing is written to cache once, then re-read on every main turn

### The Calculation

```
Built-in Listing Cost =
  (listing_tokens × main_model_input_price)
  × (cache_write once + cache_read × (main_turns - 1))

Shortlist Notes Cost =
  (note_tokens × main_model_input_price × cache_write)
  × number_of_shortlist_calls

Jev Cost =
  SUM of (requests × $0.04/1M + output × $0) from skills logs

Net Savings = Listing Cost - Notes Cost - Jev Cost
```

**Example**: You have 200 skills (≈5,000 tokens). Over 10 main turns, 2 shortlists run.
- Listing cost: 5k × $3 × (1.25 write + 0.1 read × 9) ≈ $22.35
- Shortlist notes: 600 tokens × $3 × 1.25 × 2 calls ≈ $4.50
- Jev: 2 calls × ~2k tokens × $0.04/1M ≈ $0.00016
- **Net saved: $22.35 - $4.50 - $0.00016 ≈ $17.85**

### Why This Works
- The built-in listing is **static**: same text, re-sent every request, burned to cache
- A shortlist is **dynamic**: only includes relevant skills, small, written once per call
- Jev is cheap, so even expensive shortlisting can save money if it shrinks what you send

### When to Trust This
- ✅ Skill roster is **measured** (real files on disk)
- ✅ Jev cost is **measured** (from the logs)
- ⚠️ Listing and note sizes are **estimated** (4 chars/token is a rough average)
- ⚠️ Cache behavior is **assumed** (assumes 5-minute TTL; short-lived cache makes listing cheaper)

---

## How to Interpret the Reports

### "Measured" vs "Estimated"
- **Measured**: From your session logs. Real token counts from Claude or Jev APIs. Trust these fully.
- **Estimated**: Calculated or assumed. Valid but approximate; gets better as your session runs.

### Negative Savings ("Net Extra")
If a report shows "net extra" instead of "net saved," the optimization *cost more* than the alternative:
- **Compacter**: Jev's cost or re-read overhead exceeded the summary savings. Try aggressive pruning settings.
- **Router**: Subagents cost more than having the main loop do the work. Consider higher-tier subagent models.
- **Skills**: The shortlist cost or listing size makes it cheaper to just send the listing. Consider fewer skills.

### Why Estimates Change
- **First compaction**: Uses 10% output/kept assumptions until a summary runs; updates to real percentages after.
- **First route decision**: Uses the session model's price for comparison; adjusts if you later change models.
- **First shortlist**: Uses 4 chars/token; refines over more calls.

---

## Customizing Prices

If your pricing differs from the Claude list prices (e.g., volume discounts, custom keys), edit [`core/pricing.py`](src/optim_jev/core/pricing.py):

```python
CLAUDE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "opus": (5.0, 25.0),      # (input, output) per 1M tokens
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}
CACHE_READ = 0.1       # 10% of input price
CACHE_WRITE = 1.25     # 125% of input price
```

After editing, run `/jev-compact stats`, `/jev-route stats`, or `/jev-skills stats` again. Old sessions' numbers remain unchanged (prices are saved in the logs).

---

## Questions?

- **"Why is my compaction not saving money?"** Check: is Jev pruning deep enough? Do summaries actually shrink your context? Try stricter thresholds in `/config`.
- **"Why does routing cost more than I expected?"** Subagent cache writes add up. Try routing larger tasks or routing to the same model for multiple related subtasks.
- **"Are these numbers accurate?"** Yes for measured quantities (tokens, Jev cost). Estimates improve as your session grows. Verify once a week by comparing projected vs actual.
