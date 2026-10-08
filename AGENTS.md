# Repository Guidelines

## Project Structure & Module Organization

`src/optim_jev/` contains the Python implementation. Shared utilities live in `core/`; each feature is isolated under `tools/jev_compacter`, `tools/jev_router`, or `tools/jev_skills`. Keep decisions and policy in Python so they remain easy to test. `hooks/optim-jev.ts` is the thin Claude Code integration layer, with shared TypeScript helpers in `hooks/router-lib.ts`. Python tests are named `tests/test_*.py`; Claude Code integration tests use `tests/*.test.ts`. Documentation belongs in `docs/`, plugin metadata in `.claude-plugin/`, and committed images in `assets/`.

## Build, Test, and Development Commands

The project requires Python 3.10+ and has no runtime Python dependencies.

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test_*.py"
npx -p typescript@5 tsc --noEmit -p .
python -m pip install -e .
```

The first command runs all Python unit tests. The second type-checks hooks without emitting files. The optional editable install makes `optim_jev` importable during local development. TypeScript tests run through Claude Code's plugin test runner because they import `claude-code/testing`.

## Coding Style & Naming Conventions

Use four spaces, type hints, and Python 3.10 syntax. Prefer frozen dataclasses for values passed between modules. Use `snake_case` for Python functions/modules, `PascalCase` for classes, and camelCase for TypeScript identifiers. Keep Python standard-library-only, hooks small, and all failures fail-open so plugin errors never block the user's work. Log raw values to append-only JSONL session logs; suffix estimates with `_est`. System-prompt text must remain stable between turns to preserve prompt caching.

## Testing Guidelines

Use `unittest` and inject a `FakeJev`; tests must never contact the real API. Add focused coverage beside the affected tool and name cases `test_<behavior>`. Run both the Python suite and TypeScript check before submitting. Update `tests/*.test.ts` when hook events, commands, or Python bridge payloads change.

## Commit & Pull Request Guidelines

History is small, but uses concise subjects and conventional prefixes such as `fix:`. Write imperative, scoped messages (for example, `fix: preserve router rules on init`). Keep each PR to one logical change, explain user-visible behavior, link relevant issues, and include tests. Update the corresponding `docs/` page for workflow changes; refresh `architecture.html` and affected assets when diagrams or flows change. Never commit API keys or local `.env` contents.
