<div align="center">

# optim-jev

**Spend fewer tokens in long Claude Code sessions—without changing how you work.**

Jev-powered context compaction, model routing, and skill selection in one Claude Code plugin.

[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757?style=flat-square)](https://code.claude.com/docs/en/overview)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![GitHub stars](https://img.shields.io/github/stars/Oqura-ai/optim-jev?style=flat-square&logo=github&label=Stars)](https://github.com/Oqura-ai/optim-jev/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/Oqura-ai/optim-jev?style=flat-square&logo=github&label=Forks)](https://github.com/Oqura-ai/optim-jev/forks)
[![GitHub issues](https://img.shields.io/github/issues/Oqura-ai/optim-jev?style=flat-square&logo=github)](https://github.com/Oqura-ai/optim-jev/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](#license)
[![Our Discord](https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/EpUxGjNBva)

[Get started](#quick-start) · [Documentation](docs/README.md) · [Architecture](docs/architecture.md) · [Contributing](docs/contributing.md)

<img src="assets/optim-jev.png" alt="optim-jev architecture: context compaction, model routing, and skill selection" width="100%">

</div>

## Why optim-jev?

Long agent sessions accumulate stale tool output, send oversized skill catalogs, and use the main model for work a smaller model could handle. optim-jev reduces that overhead at three points while keeping Claude Code's normal workflow intact.

Each tool works independently, fails open if unavailable, and includes a `stats` command that reports session-level cost and savings in US dollars.

## Three tools, one plugin

| Tool | What it does | Default | Learn more |
|---|---|:---:|---|
| **jev-compacter** | Removes stale tool calls and outputs instead of summarizing away the whole conversation | On | [Guide](docs/jev-compacter.md) |
| **jev-router** | Routes file changes to the right model using project-specific rules that evolve with your workflow | Off | [Guide](docs/jev-router.md) |
| **jev-skills** | Sends a short, relevant skill list for each prompt instead of the entire catalog | Off | [Guide](docs/jev-skills.md) |

<details>
<summary><strong>jev-compacter — preserve useful context</strong></summary>

<br>
<img src="assets/jev-compacter.png" alt="jev-compacter session statistics" width="100%">

It works automatically with `/compact` and auto-compaction. Inspect the current session with:

```text
/jev-compact stats
```

</details>

<details>
<summary><strong>jev-router — use the right model for each edit</strong></summary>

<br>
<img src="assets/jev-router.png" alt="jev-router model routing decisions" width="100%">

```text
/jev-route init "what matters in this project"
/jev-route on | off
/jev-route why | stats
```

Tell Claude to change a preference later—for example, “let haiku edit the tests”—and the project rules update with your workflow.

</details>

<details>
<summary><strong>jev-skills — load only relevant skills</strong></summary>

<br>
<img src="assets/jev-skills.png" alt="jev-skills prompt shortlist" width="100%">

```text
/jev-skills on | off
/jev-skills scope project | global
/jev-skills why | stats | reindex
```

</details>

## Quick start

### Requirements

- [Claude Code](https://code.claude.com/docs/en/overview) with plugin support
- Python 3.10 or newer
- A TypeSafe API key for Jev

### Install

```bash
git clone https://github.com/Oqura-ai/optim-jev.git
claude plugin marketplace add ./optim-jev
claude plugin install optim-jev@optim-jev
```

Set the key in Claude Code under `/config` → **TypeSafe API key**, or export it before starting Claude Code:

```bash
export TYPESAFE_API_KEY="your-key"
```

Restart Claude Code. jev-compacter is ready immediately; enable the router and skill picker when you want them. See [Getting started](docs/getting-started.md) for every command, option, and troubleshooting step.

> [!NOTE]
> The plugin uses only Python's standard library. Your API key is passed to child processes through the environment and is never written to project files or logs.

## Documentation

| Resource | What you will find |
|---|---|
| [Getting started](docs/getting-started.md) | Installation, configuration, commands, and troubleshooting |
| [Performance metrics](docs/performance-metrics.md) | How token usage, cost, and estimated savings are calculated |
| [Architecture](docs/architecture.md) | The TypeScript-to-Python bridge, data flow, and session logs |
| [Contributing](docs/contributing.md) | Local setup, tests, conventions, and pull requests |

## Community and support

- Found a bug or have a feature idea? [Open an issue](https://github.com/Oqura-ai/optim-jev/issues/new/choose).
- Want to help? Read the [contributing guide](docs/contributing.md) and submit a focused pull request.
- For the wider Claude Code community, join the official [Claude Developers Discord](https://anthropic.com/discord).

## License

optim-jev is released under the MIT License.

<div align="center">

Built by [Oqura.ai](https://github.com/Oqura-ai) for more efficient Claude Code workflows.

</div>
