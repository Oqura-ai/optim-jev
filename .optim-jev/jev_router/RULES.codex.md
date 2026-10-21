# Codebase context for Codex routing

Written by `optim-jev codex setup`; edit freely. `## General` facts go with every plan;
a `## <path>` section is sent only when a planned file is under that path.

## General

- Claude and Codex have separate adapters, model aliases, policy files, caches, and logs.
- Codex uses fast, balanced, and strong tiers; never write Anthropic aliases into Codex files.
- Transcript compaction and the AbovePrompt dashboard are Claude-only.
- .env may hold secrets; never read, edit, or print it.

## codex-plugin/

- Keep this package to its manifest, hook declarations, and fail-open launcher; Python implementation belongs in src/optim_jev/.

## hooks/

- Claude system-prompt text must remain stable between turns for prompt caching.

## src/optim_jev/

- Shared routing and skill decisions belong under tools/; hosts/codex.py only translates Codex wire formats.
