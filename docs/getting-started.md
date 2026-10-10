# Getting started

## Requirements

- Claude Code with plugin support
- Python 3.10 or newer on your `PATH` (or set its path in the `python` option)
- A TypeSafe API key for Jev

No Python packages need installing: the tools use the standard library only.

## Install

The repository is its own plugin marketplace (`.claude-plugin/marketplace.json`).

```bash
git clone https://github.com/Oqura-ai/optim-jev.git
claude plugin marketplace add ./optim-jev
claude plugin install optim-jev@optim-jev
```

Restart Claude Code. The dashboard above the prompt shows all three tools, the current context fill, and their latest decisions:

```
optim-jev | Context 12% · soft 60% · hard 85% | Router off | Skills off
```

Its buttons compact now or toggle the router and skill picker. Set **Dashboard** to `off` in `/config` to use the compact status line instead.

The terminal dashboard adapts to both its width and the height Claude allocates
above the prompt. With at least 60 columns and five rows, it keeps the full card.
Smaller allocations use a borderless, single-line status, with a second row of
buttons when at least 50 columns and two rows fit. Long status text is truncated;
the panel does not add rows for decoration or wrapped controls. With no allocated
space, it renders nothing. `/compact`, `/jev-route on|off`, and `/jev-skills on|off`
remain available when buttons do not fit. The desktop layout is unchanged.

## Set your API key

Use any one of these, checked in this order:

1. The plugin option **TypeSafe API key** in `/config`
2. The environment variable `TYPESAFE_API_KEY`
3. `TYPESAFE_API_KEY` in the `env` block of your Claude Code settings

The key is passed to the Python tools through their environment, never written to disk or logs. A `.env` file in your project is **not** read.

## Use each tool

### jev-compacter: on by default

Nothing to do. `/compact` and Claude Code's auto-compaction now prune stale context with Jev, and it also runs on its own after a turn once the context is 60% full.

```
/jev-compact stats     what compaction cost this session, vs the built-in summary
```

Figures marked `(est.)` in `stats` are estimates. Unmarked figures are measured from the session.

### jev-router: off by default

```
/jev-route init                      draft rules for this project, then turn routing on
/jev-route init "docs only by haiku" the same, with your preferences
/jev-route init --force              redraft rules that already exist (old ones kept as *.bak)
/jev-route on | off                  routing for this session
/jev-route why                       the last 5 routing decisions
/jev-route stats                     cost vs the main model doing the work
```

With routing on, Claude changes files through subagents and Jev picks each subagent's model. To change a preference later, just tell Claude ("let haiku edit the tests"); it updates `.optim-jev/jev_router/rules.json` or `RULES.md` itself.

### jev-skills: off by default

```
/jev-skills on | off                 the picker for this session
/jev-skills scope project | global   which skills are in scope
/jev-skills why                      the last shortlist
/jev-skills stats                    cost vs the built-in skill list
/jev-skills reindex                  rebuild the skill index
```

## Options

Set in `/config` under the plugin. All are optional.

| Option | Default | Effect |
|---|---|---|
| `python` | `python` | Python executable used to run the tools |
| `jev_dashboard_mode` | `on` | `off` hides the dashboard and restores the status line |
| `jev_compacter_mode` | `on` | `off` returns to Claude Code's built-in summary |
| `jev_compacter_soft_percent` | 60 | context fill at which pruning is tried after a turn |
| `jev_compacter_hard_percent` | 85 | fill at which compaction must shrink the context |
| `jev_compacter_target_percent` | 40 | a prune landing at or below this is always applied |
| `jev_compacter_min_freed_tokens` | 8000 | above the target, a prune must free at least this much |
| `jev_compacter_keep_threshold` | 0.5 | Jev probability a tool call needs to stay |
| `jev_compacter_preserve_recent_messages` | 6 | newest messages never touched |
| `jev_router_mode` | `off` | routing default for new sessions |
| `jev_router_cap` | `on` | Jev never picks a model above the session's |
| `jev_router_escalate_after` | 3 | failed writes before the next subagent goes up a model |
| `jev_router_init_model` | `sonnet` | model that drafts the rules during init |
| `jev_router_max_input_tokens` | 4000 | most tokens sent to Jev per routing decision |
| `jev_router_decider_model` | `haiku` | decides instead of Jev when its input stays over the cap |
| `jev_skills_mode` | `off` | picker default for new sessions |
| `jev_skills_scope` | `project` | `global` adds `~/.claude/skills` and plugin skills |
| `jev_skills_max_picks` | 3 | most skills shortlisted per prompt |
| `jev_skills_min_percent` | 30 | Jev's share a skill needs to be shortlisted |
| `jev_skills_max_input_tokens` | 3000 | most tokens sent to Jev per shortlist request |

## What gets written to your project

Everything goes into `.optim-jev/`, created on first use. It ignores itself in git, except the router's `rules.json` and `RULES.md`, which are meant to be committed and shared with your team.

## Troubleshooting

| Symptom | Check |
|---|---|
| `hooks module did not load` | reload the plugin; the message names the file and line |
| `python exited 1` / `not found` | set the `python` option to a Python 3.10+ path |
| `TYPESAFE_API_KEY is not configured` | set the key (above) |
| compaction always falls back to the summary | `/jev-compact stats`: Jev may be failing, or freeing too little |
| a routed write is refused | the message names the rule in `rules.json`; ask Claude to change it if it's wrong |
