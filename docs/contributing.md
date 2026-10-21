# Contributing

Read [Architecture](architecture.md) first: decisions belong in shared Python; Claude TypeScript and
Codex Python are thin, explicit host adapters.

## Setup

```bash
git clone https://github.com/Oqura-ai/optim-jev.git
cd optim-jev
python --version            # 3.10+; runtime is standard-library-only
python -m pip install -e .  # installs the optim-jev CLI for Codex development
```

To try your changes in Claude Code, install the plugin from your clone (see [Getting started](getting-started.md#install)) and reload it after each change. A hooks file that fails to parse is reported on reload with its line number.

For Codex, use the isolated marketplace workflow in [Codex support](codex.md#install-from-github). Keep real
credentials out of automated smoke environments, and create temporary `CODEX_HOME` directories
outside the checkout so plugin installation cannot recursively copy its own cache.

To test an unreleased Codex build without an editable install:

```powershell
py -3 -m pip uninstall -y optim-jev
py -3 -m pip install .
optim-jev codex install --marketplace .
```

This matches the release layout: Python is installed normally and Codex caches only the three-file
plugin. Run `optim-jev codex uninstall` before repeating the installation test.

## Tests

```bash
# Python (standard library unittest)
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"

# TypeScript type check after Claude has generated .claude-plugin/types/
npx -p typescript@5 tsc --noEmit -p .

# Claude integration contracts
claude plugin validate .
claude plugin test .
```

`tests/*.test.ts` use Claude Code's own `claude-code/testing` module and run inside Claude Code's plugin test runner.

Python tests never call the real Jev API: they pass a `FakeJev` with an `ask(state, questions)` method (and `usage()`), which is all the tools need.

## Where things go

| Change | Side | Where |
|---|---|---|
| a decision (what to prune, which model, which skills) | Python | the tool's `policy.py` / `logic.py` / `pick.py` |
| a new command or subcommand | both | `command.run` handler in the hook, new mode in the tool's `HANDLERS` |
| reacting to a new Claude Code event | TypeScript | `register()` in `hooks/optim-jev.ts` |
| reacting to a Codex event | Python | `hosts/codex.py` and `codex-plugin/hooks/codex-hooks.json` |
| a deterministic Codex command | Python | `src/optim_jev/cli.py`; never put control actions in a skill prompt |
| a new user option | both | `.claude-plugin/plugin.json` + the tool's `config.py` |
| a Codex-local option | Codex adapter | `.optim-jev/config.json` / `OPTIM_JEV_*`; never rewrite `~/.codex/config.toml` |
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
- If you change a workflow, update its page and diagrams in [`architecture.md`](architecture.md), plus any affected images in `assets/`.
