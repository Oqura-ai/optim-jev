# OpenAI Codex support

optim-jev extends its model router to Codex CLI and Codex desktop through a separate host adapter.
Claude Code keeps the full three-tool experience; Codex receives the features its public hooks can
implement reliably.

| Feature | Codex support |
|---|---|
| Subagent model and effort routing | Yes |
| Path write/delete rules | Yes, as a workflow guardrail |
| Failure escalation | Yes |
| Skill shortlist | Experimental, advisory, off by default |
| Transcript compaction | No; Codex hooks cannot replace live history |
| AbovePrompt dashboard and slash commands | No |
| Exact token and cost reports | No stable Codex usage feed |

## Requirements

- Codex CLI 0.162.1 or newer
- Python 3.10 or newer
- A TypeSafe API key for Jev
- A Git repository for each project you configure

The Python implementation uses only the standard library. Keys are read from the process
environment and are never written to project files or logs.

## Install from GitHub

optim-jev is not assumed to be published to PyPI. Install the Python package directly from GitHub,
then let its CLI install the small Codex plugin:

### Windows PowerShell

```powershell
$key = Read-Host "TypeSafe API key"
$env:TYPESAFE_API_KEY = $key
[Environment]::SetEnvironmentVariable("TYPESAFE_API_KEY", $key, "User")
Remove-Variable key

py -3 -m pip install "https://github.com/Oqura-ai/optim-jev/archive/refs/heads/main.zip"
optim-jev codex install
```

### macOS or Linux

```bash
export TYPESAFE_API_KEY="your-key"
python3 -m pip install "https://github.com/Oqura-ai/optim-jev/archive/refs/heads/main.zip"
optim-jev codex install
```

Start Codex, run `/hooks`, review and trust every optim-jev hook, then restart Codex. Installing or
updating a plugin does not automatically trust its hooks. The Python package owns the implementation;
the Codex plugin cache receives only its manifest, hook declarations, and fail-open launcher.

For an unreleased local checkout, use this instead:

```powershell
py -3 -m pip install .
optim-jev codex install --marketplace .
```

## Configure a project

Run setup from the Git repository where you want routing:

```powershell
cd C:\path\to\project
git rev-parse --show-toplevel
optim-jev codex setup
optim-jev codex status
```

Setup reads the models available to the current Codex account and asks you to map three neutral
capability tiers:

- `fast`: mechanical edits, tests, documentation, and renames
- `balanced`: feature work and refactors in known patterns
- `strong`: hard debugging, architecture, and subtle invariants

The mapping is validated before routing is enabled. Codex never uses Claude's Haiku, Sonnet, or
Opus aliases.

Project state is separated by host:

```text
.optim-jev/
├── config.json                    local Codex feature settings
└── jev_router/
    ├── models.codex.json          local account-specific model IDs
    ├── rules.codex.json           commit-ready Codex path policy
    └── RULES.codex.md             commit-ready Codex context
```

Claude continues to use `models.json`, `rules.json`, and `RULES.md`.

## Use it

Start Codex from the configured repository:

```powershell
codex
```

Model routing is automatic whenever Codex spawns a subagent. To inspect the latest decision:

```text
!optim-jev codex why
```

Useful terminal commands:

```text
optim-jev codex setup
optim-jev codex on
optim-jev codex off
optim-jev codex status
optim-jev codex status --json
optim-jev codex why
optim-jev codex why --session SESSION_ID
optim-jev codex skills-on
optim-jev codex skills-off
optim-jev codex uninstall
```

These are deterministic local commands, not prompts sent to Codex. Inside Codex, prefix them with
`!`, for example `!optim-jev codex status`.

### Verify routing

Ask Codex:

```text
Call spawn_agent exactly once to review README.md and report one improvement. Do not edit files.
```

Then run:

```text
!optim-jev codex why
```

A healthy result names `fast`, `balanced`, or `strong`, says `via jev`, and includes model and effort
probabilities.

### Optional skill shortlist

```text
!optim-jev codex skills-on
```

The shortlist advises Codex which existing skill may fit a root prompt. It does not replace Codex's
native progressive-disclosure skill catalogue, so optim-jev does not claim skill-token savings on
Codex. If Jev is unavailable, no shortlist text is injected.

## How it works

The GitHub repository exposes a Codex marketplace:

```text
.agents/plugins/marketplace.json
codex-plugin/
├── .codex-plugin/plugin.json
└── hooks/
    ├── codex-hooks.json
    └── run-codex-hook.py
```

The launcher imports the installed `optim_jev` Python package. Keeping implementation code outside
the plugin cache prevents source trees, Git data, runtime logs, tests, and build output from being
copied into a user's Codex home.

The adapter uses four Codex events:

1. `SessionStart` adds stable delegation and policy instructions.
2. `UserPromptSubmit` records recent root prompts and optionally requests a skill shortlist.
3. `PreToolUse` routes `collaborationspawn_agent` calls and checks recognized writes.
4. `PostToolUse` links child agents, records failures, and escalates repeated failures.

Codex Multi-Agent V2 exposes delegated instructions to local hooks as ciphertext. optim-jev never
modifies that ciphertext. It routes from the visible task name and recent root prompts, preserves
unknown spawn fields, applies the validated model ID and effort, and isolates the child turn when
the model changes.

Routing decisions stay in the shared Python engine. Only host boundaries differ:

- Claude: TypeScript adapter, Haiku/Sonnet/Opus, full compaction/UI/cost support.
- Codex: Python adapter, fast/balanced/strong, router plus advisory skills.

Codex logs use separate host-specific folders and locked append-only JSONL writes. Claude retains
its original log behavior and filenames.

## Failure and security behavior

- Jev unavailable: use a deterministic available fallback or leave native behavior unchanged.
- Invalid model catalogue: do not rewrite the spawn.
- Malformed hook input or adapter error: return valid empty output and fail open.
- Repeated failed subagent writes: escalate the next task touching those files.
- Explicit policy denial: remain denied even if audit logging fails.

The write guard is not a security sandbox. Shell parsing is necessarily heuristic and hook coverage
is incomplete. Continue using Codex sandbox and approval settings as the security boundary.

## Troubleshooting

### `TYPESAFE_API_KEY` is missing

The key configured in Claude's `/config` is not available to Codex. Set it before starting Codex,
stop stale Codex processes, and verify:

```powershell
$env:TYPESAFE_API_KEY = Read-Host "TypeSafe API key"
Get-Process codex -ErrorAction SilentlyContinue | Stop-Process -Force
optim-jev codex status
```

Status must say `TYPESAFE_API_KEY: present`.

### Routing says `via fallback`

Run `optim-jev codex why`. A missing key, unavailable Jev service, or invalid answer is shown there.
Fallback is deliberate fail-open behavior, not silent routing.

### Codex prints `No agents completed yet`

If a separate `Completed /root/...` event and a final answer appear, the agent completed. This is a
Codex Multi-Agent V2 wait-display timing issue, not a routing failure.

### Hook import fails

The hook runs `py -3` on Windows. Install with that same interpreter:

```powershell
py -3 -m pip install --force-reinstall "https://github.com/Oqura-ai/optim-jev/archive/refs/heads/main.zip"
py -3 -m pip show optim-jev
```

Restart Codex afterward.

### Wrong project or no configuration

```powershell
git rev-parse --show-toplevel
optim-jev codex status
```

Commands search upward for the nearest `.git` directory. Run setup again from the intended project.

## Uninstall

```powershell
optim-jev codex uninstall
py -3 -m pip uninstall optim-jev
```

This removes optim-jev's Codex plugin and marketplace. It does not delete projects, Codex sessions,
or unrelated plugins.

## Technical references

- [Codex plugins](https://developers.openai.com/codex/plugins)
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Subagents](https://developers.openai.com/codex/subagents)
- [Agent Skills](https://developers.openai.com/codex/skills)
