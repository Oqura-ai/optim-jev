# optim-jev

optim-jev is a Claude Code plugin (version 0.1.0, MIT license) that reduces token usage in long Claude Code sessions. It uses Jev, a model that makes the decisions for three tools: a context compacter, a subagent model router, and a skill picker. Each tool can be switched on or off on its own. All per-project data is stored in a `.optim-jev/` folder inside your project.

## Features

- **Jev Compacter** (`jev_compacter`) replaces the built-in `/compact` summary with a pruning pass. It drops or truncates stale tool calls and tool results and keeps everything else verbatim.
- **Jev Router** (`jev_router`) picks the model for each subagent that edits files, choosing from opus, sonnet, and haiku. It moves a subagent up one model after repeated failed edits.
- **Jev Skills picker** (`jev_skills`) sends Claude a short list of relevant skills for each prompt instead of the full skill list.

## Installation & configuration

Requirements:

- Python 3.10 or newer.
- A TypeSafe API key, set either through the plugin option `typesafe_api_key` or the environment variable `TYPESAFE_API_KEY`.

Plugin options:

- `python` sets the Python executable used to run the tools. Default: `python`.
- `typesafe_api_key` is your TypeSafe API key.
- `jev_compacter_mode` turns the compacter on or off. Default: `on`.
- `jev_router_mode` sets the router default. Default: `off`.
- `jev_skills_mode` sets the skills picker default. Default: `off`.

The router and skills picker can also be toggled per session with `/jev-route on|off` and `/jev-skills on|off`.

Per-project data lives in `.optim-jev/`:

- `.optim-jev/logs/` holds logs.
- `.optim-jev/jev_router/` holds router rules (`rules.json` and `RULES.md`).
- `.optim-jev/jev_skills/` holds the skill index (`index.json`).

The hook file `hooks/optim-jev.ts` bridges Claude Code and the Python tools. It reads one JSON request on stdin and writes one JSON answer on stdout. `hooks/hooks.json` is the minimal manifest. `hooks/hooks.reference.jsonc` documents the hook events for reference only; it is not loaded.

## Tool workflows

### Jev Compacter

1. Triggers: a turn ends with context fill above the soft threshold (default 60%), or idle time passes the prompt-cache window while fill is above the target.
2. Jev reviews the conversation and decides which stale tool calls and tool results to drop or truncate. Everything else is kept verbatim.
3. Pruning aims for the target fill (default 40%) and must free at least 8000 tokens by default. The six most recent messages are always kept.
4. At the hard threshold (default 85%), compaction must shrink the context. If pruning is not enough, the built-in summary is used as a fallback.
5. What you see: a smaller context in place of a summary, unless the fallback runs.

### Jev Router

1. Setup: run `/jev-route init`. The scanner (`scan.py`) reads the project tree, respects `.gitignore` through `git ls-files`, and skips folders such as `node_modules` and `dist`.
2. A rules writer model (default sonnet) drafts `.optim-jev/jev_router/rules.json` and `RULES.md` from the scan.
3. When the router is on, the main model changes files only through subagents.
4. Jev picks each subagent's model from the ladder: opus for cross-module design and hard debugging, sonnet for most feature work, and haiku for mechanical edits, tests, and docs.
5. The cap option (default on) stops Jev from choosing a model above the session's model.
6. After three failed edits by one subagent (the default), the next subagent for those files starts one model up.
7. What you see: the chosen model for each subagent. Use `/jev-route why` to see the reason for the last pick and `/jev-route stats` for totals.

### Jev Skills picker

1. Turn it on with `jev_skills_mode` or `/jev-skills on`.
2. The skill index is built in `.optim-jev/jev_skills/index.json` and rebuilt when a `SKILL.md` file changes. Run `/jev-skills reindex` to rebuild it by hand.
3. Scope is `project` by default, meaning `.claude/skills` in this project. Set `global` to also include `~/.claude/skills` and the skills of installed plugins.
4. For each prompt, the full skill list is left out of what Claude receives. Jev shortlists the skills that prompt needs. The default shortlist size is 3 (allowed range 1 to 10).
5. What you see: fewer skills offered per prompt. Use `/jev-skills why` and `/jev-skills stats` to inspect the picks.

## Commands

| Command | Purpose |
| --- | --- |
| `/jev-route on\|off` | Turn the router on or off for this session |
| `/jev-route init` | Scan the project and draft router rules |
| `/jev-route why` | Explain the last model pick |
| `/jev-route stats` | Show router totals |
| `/jev-skills on\|off` | Turn the skills picker on or off for this session |
| `/jev-skills scope project\|global` | Set the skill search scope |
| `/jev-skills why` | Explain the last shortlist |
| `/jev-skills stats` | Show skills picker totals |
| `/jev-skills reindex` | Rebuild the skill index |
