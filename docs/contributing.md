# Contributing

Read [Architecture](architecture.md) first: every change sits on one side of the TypeScript ↔ Python bridge, and knowing which side matters.

## Setup

```bash
git clone https://github.com/Oqura-ai/optim-jev.git
cd optim-jev
python --version            # 3.10+; no packages to install
```

To try your changes in Claude Code, install the plugin from your clone (see [Getting started](getting-started.md#install)) and reload it after each change. A hooks file that fails to parse is reported on reload with its line number.

## Tests

```bash
# Python (standard library unittest)
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"

# TypeScript type check (TypeScript isn't a project dependency; any 5.x works)
npx -p typescript@5 tsc --noEmit -p .
```

`tests/*.test.ts` use Claude Code's own `claude-code/testing` module and run inside Claude Code's plugin test runner.

Python tests never call the real Jev API: they pass a `FakeJev` with an `ask(state, questions)` method (and `usage()`), which is all the tools need.

## Where things go

| Change | Side | Where |
|---|---|---|
| a decision (what to prune, which model, which skills) | Python | the tool's `policy.py` / `logic.py` / `pick.py` |
| a new command or subcommand | both | `command.run` handler in the hook, new mode in the tool's `HANDLERS` |
| reacting to a new Claude Code event | TypeScript | `register()` in `hooks/optim-jev.ts` |
| a new user option | both | `.claude-plugin/plugin.json` + the tool's `config.py` |
| something to log | Python | append a record with a new `kind` to the session log |
| a cost comparison | Python | the tool's stats code + [`core/pricing.py`](../src/optim_jev/core/pricing.py) |

### Adding a Python mode

```python
# src/optim_jev/tools/<tool>/tool.py
def my_mode(request: dict[str, Any]) -> dict[str, Any]:
    project, session_id = request["project_dir"], request["session_id"]
    ...
    return {"text": "..."}

HANDLERS = {..., "my_mode": my_mode}
```

```typescript
// hooks/optim-jev.ts
const { text } = await runTool<{ text: string }>($, options, ROUTER_MODULE, 'my_mode', await routerFields($));
```

## Conventions

- **Fail open.** If Python fails, the hook falls back to Claude Code's own behaviour. Never block the user's work because the plugin broke.
- **Keep the hook thin.** Logic belongs in Python, where it's testable without Claude Code.
- **Per-session logs only.** Append to `logs/<tool>/<session>.jsonl` via [`core/logs.py`](../src/optim_jev/core/logs.py). Never rewrite a log.
- **Record raw numbers.** Log token counts, not dollars; prices are applied when stats are shown. Label anything estimated with an `_est` suffix.
- **Static prompt text.** Anything added to the system prompt must be identical every turn, or it breaks the prompt cache.
- **No new dependencies** in Python; standard library only.
- **No secrets on disk.** The API key travels in the child's environment only.
- Python 3.10+, type hints, frozen dataclasses for data passed between modules.

## Pull requests

- One change per PR, with tests for any Python behaviour you change.
- Run both test commands above before opening it.
- If you change a workflow, update its page in `docs/` and, if the flow changed, the diagrams in [`architecture.html`](../architecture.html) and `assets/`.
