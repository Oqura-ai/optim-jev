# jev-skills

![jev-skills](../assets/jev-skills.png)

Claude Code normally sends the description of every installed skill with every request. With the picker on, that list is replaced by a one-line note, and Jev attaches a shortlist of the few skills each new prompt actually needs.

## Scope

| Scope | Skills |
|---|---|
| `project` (default) | `.claude/skills` in this project |
| `global` | also `~/.claude/skills` and installed plugins' skills |

In global scope, Claude may read the shortlisted skills' folders without asking. The roster is cached in `.optim-jev/jev_skills/index.json`; `/jev-skills reindex` rebuilds it.

## One prompt, step by step

1. **Skip?** No shortlist for slash commands, prompts under 12 characters, or follow-ups like "yes", "ok", "continue".
2. **Trim**: over 40 skills, a keyword match against the prompt keeps the 40 closest.
3. **Batches**: skills are split into groups of 20. Jev picks the best fit in each group, with "none" always an option.
4. **Final round**: with more than one group, the top 2 of each (at 15% or more) are scored together once more.
5. **Shortlist**: up to 3 skills that beat "none" and reach 30%.

| Result | What Claude receives |
|---|---|
| shortlist | the skills with their descriptions and percentages, and a note to load one if it fits |
| no match | nothing extra |
| Jev offline | the names of every skill in scope |

Jev sees the prompt and your 3 prompts before it (your own text only), so follow-ups are judged in context. Each request to Jev is capped (`jev_skills_max_input_tokens`, default 3000): earlier prompts are dropped oldest first, and skills are split into smaller batches so each batch fits.

## Files

| File | Role |
|---|---|
| [`tool.py`](../src/optim_jev/tools/jev_skills/tool.py) | entry point: modes `index`, `shortlist`, `loaded`, `why`, `stats` |
| [`pick.py`](../src/optim_jev/tools/jev_skills/pick.py) | trim, batches, final round |
| [`index.py`](../src/optim_jev/tools/jev_skills/index.py) | finds every `SKILL.md` in scope |
| [`config.py`](../src/optim_jev/tools/jev_skills/config.py) | defaults |

## Known gaps

- The keyword trim can drop a relevant skill whose description shares no words with the prompt.
- Shortlist notes are new text on each prompt, so they're written to the prompt cache rather than read from it.
