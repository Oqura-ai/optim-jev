# Codebase context for model routing

Written by `/jev-route init`; edit freely. `## General` facts go with every plan;
a `## <path>` section is sent only when a planned file is under that path.

## General

- Repo holds a nested second plugin, fast-jev-compaction/, with its own package.json, tsconfig and tests.
- Router logic exists in both TypeScript (hooks/) and Python (src/optim_jev/); tests exist for each in tests/.

## .env

- Environment secrets file; never print or commit its contents.

## hooks/hooks.json

- Minimal manifest; the commented documentation lives in hooks/hooks.reference.jsonc, since plain JSON cannot hold comments.
