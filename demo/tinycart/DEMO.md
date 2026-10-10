# optim-jev demo: TinyCart

This demo shows the skill picker, model router, and context compacter in one real workflow. Allow about 6–8 minutes.

## Before recording

1. Install optim-jev and configure `TYPESAFE_API_KEY`.
2. Open a fresh terminal in this directory.
3. Check the toy project:

   ```text
   python run_tests.py
   ```

4. Start a fresh Claude Code session and enable the two opt-in tools:

   ```text
   /jev-skills on
   /jev-route on
   ```

The compacter is already on by default. The committed router rules make the routing segment deterministic without requiring `/jev-route init` during the recording.

## Scene 1 — pick one relevant skill

Prompt:

```text
Audit data/inventory.csv for duplicate SKUs and low stock. Use the relevant project skill, run its verbose trace, and write reports/inventory-audit.md.
```

Then inspect the decision:

```text
/jev-skills why
/jev-skills stats
```

What to point out:

- the project contains four skills, but only the inventory audit skill is attached;
- Claude follows that skill’s repeatable audit procedure;
- the verbose trace creates realistic disposable context for the compacter scene;
- the generated report is routed under the low-risk `reports/` rule.

## Scene 2 — route work by risk

First, make a low-risk documentation edit:

```text
Add a short "Inventory checks" section to docs/checkout.md that links to reports/inventory-audit.md.
```

Then make a pricing edit:

```text
Add a vip_price helper to src/tinycart/pricing.py. It must apply a whole-number percentage discount, never return negative cents, and use integer arithmetic only. Do not edit any other file.
```

Inspect the routes:

```text
/jev-route why
/jev-route stats
```

What to point out:

- docs and reports are explicitly safe for Haiku;
- pricing requires Sonnet or stronger because it handles money invariants;
- `/jev-route why` shows the selected model, source, allowed models, and matching path rule.

Run one final read-only turn so the earlier verbose audit is no longer among the newest messages:

```text
Run python run_tests.py and summarize the result without changing files.
```

## Scene 3 — prune stale context

Run:

```text
/compact
/jev-compact stats
```

What to point out:

- optim-jev judges old tool calls instead of replacing the entire conversation with a summary;
- the noisy inventory trace is now stale, while the requirements and recent pricing work remain intact;
- the stats distinguish measured cost from estimates.

## Closing shot

Leave the dashboard and the three styled stats outputs visible, then summarize the story:

> Pick only the skill the task needs, route the edit to the least expensive safe model, and prune tool output once it stops being useful.

## Reset

Start a new Claude Code session. The generated `reports/inventory-audit.md` and optim-jev runtime logs are ignored by Git, so they do not dirty the demo project. Restore any recorded source or documentation edits with your normal Git workflow before another take.
