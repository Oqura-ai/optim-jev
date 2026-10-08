# Codebase context for model routing

Written by `/jev-route init`; edit freely. `## General` facts go with every plan;
a `## <path>` section is sent only when a planned file is under that path.

## General

- Ignore the .optim-jev directory: it holds runtime logs and generated rules, not source.
- Documentation work (README, PERFORMANCE_METRICS.md, docs, comments) must be done only by sonnet or haiku, never opus.
- .env may hold secrets; never read, edit or print it.

## hooks/

- hooks/optim-jev.ts talks to the Python tools in src/optim_jev/tools/ via one JSON request on stdin and one JSON answer on stdout; keep both sides' schemas in sync.

## src/optim_jev/

- Each tool's tool.py is a bridge to hooks/optim-jev.ts; changing request or answer shapes requires updating the hook and tests/.
