import type { AgentSpawnInput, On } from 'claude-code';
import { describe, expect, test } from 'claude-code/testing';
import { deletedPaths, lookup, relPath } from '../hooks/router-lib';

const RENDER = {
  section: '## optim-jev model router\n(test section)',
  rules: {
    'src/core/': { write: ['opus'], delete: ['opus'] },
    'src/gen/': { write: [], delete: [] },
  },
  tiers: ['haiku', 'sonnet', 'opus'],
  current: 'sonnet',
  has_rules: true,
};

const SPAWN = {
  model: 'haiku',
  files: ['src/api/a.py'],
  appendix: '\n\n---\noptim-jev router: you run on haiku.\nCodebase context (RULES.md):\n- keep handlers thin',
  toast: 'jev · oauth handler → haiku',
  jev_failed: null,
};

/** Stands in for the engine and the Python child; records what reached them. */
function engine(on: On, failTools = false) {
  const seen = {
    modes: [] as string[],
    requests: [] as Record<string, unknown>[],
    spawned: [] as { model?: string; prompt: string }[],
    toolsRun: [] as string[],
    outcomes: [] as Record<string, unknown>[],
  };
  on('session.id', () => ({ value: 'sid-1' }));
  on('session.root', () => ({ value: '/proj' }));
  on('session.model', () => ({ value: 'claude-sonnet-5-5' }));
  on('store.get', () => ({ value: undefined }));
  on('store.set', () => ({ value: undefined }));
  on('env.get', () => ({ value: undefined }));
  on('settings.read', () => ({ value: {} }));
  on('command.register', (_$, e) => ({ value: { command: e.name } }));
  on('ui.status', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
  on('session.start', (_$, e) => ({ cwd: e.cwd }));
  on('turn.start', (_$, e) => ({ turnId: e.turnId }));
  on('turn.complete', (_$, e) => ({ text: e.answer }));
  on('process.run', (_$, e) => {
    const mode = e.argv[3] ?? '';
    const request = JSON.parse(e.init?.stdin ?? '{}');
    seen.modes.push(mode);
    seen.requests.push(request);
    if (mode === 'outcome') seen.outcomes.push(request.record);
    const answers: Record<string, unknown> = { render: RENDER, spawn: SPAWN, outcome: {} };
    return {
      value: {
        exitCode: 0,
        stdout: JSON.stringify(answers[mode] ?? {}),
        stderr: '',
        isStdoutTruncated: false,
        isStderrTruncated: false,
      },
    };
  });
  on('agent.spawn', (_$, e) => {
    seen.spawned.push({ model: e.model, prompt: e.prompt });
    return { model: e.model ?? 'claude-sonnet-5-5', agentId: `agent-${seen.spawned.length}` };
  });
  on('tool.call', (_$, e) => {
    seen.toolsRun.push(String(e.tool));
    return failTools ? { result: 'failed', isError: true } : { result: 'ok' };
  });
  return seen;
}

function spawn(prompt: string, description: string, fork = false): AgentSpawnInput {
  return {
    tool_use_id: `toolu_${description.length}`,
    prompt,
    description,
    subagentType: 'general-purpose',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-sonnet-5-5',
    background: false,
    fork,
  };
}

const START = { cwd: '/proj', surface: null, isInteractive: false } as const;
const EDIT = { tool: 'Edit', file_path: '/proj/src/api/a.py', old_string: 'a', new_string: 'b' } as const;
/** An Edit as a subagent makes it (the test kit's call type has no agentId field). */
const byAgent = (agentId: string | undefined, file_path: string = EDIT.file_path) => ({ ...EDIT, file_path, agentId }) as unknown as typeof EDIT;
const DONE = { turnId: 't1', answer: 'done', durationMs: 1, isAborted: false, reason: 'answer' } as const;

describe('jev-router', () => {
  test('on: the main loop delegates; Jev picks the subagent model; rules bind the subagent', { options: { jev_router_mode: 'on' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    await $.turn.start({ text: 'add oauth to the api', turnId: 't1' });

    const main = await $.tool.call(EDIT);
    expect(main.deny).toContain('Spawn a subagent');
    const rm = await $.tool.call({ tool: 'Bash', command: 'rm src/api/a.py' });
    expect(rm.deny).toContain('Spawn a subagent');
    const ls = await $.tool.call({ tool: 'Bash', command: 'ls src' });
    expect(ls.deny).toBeUndefined();
    expect(seen.toolsRun).toEqual(['Bash']);

    const agent = await $.agent.spawn(spawn('Add oauth to src/api/a.py', 'oauth handler'));
    expect(seen.spawned.at(-1)?.model).toBe('haiku');
    expect(seen.spawned.at(-1)?.prompt).toContain('you run on haiku');
    expect(seen.requests.at(-1)).toMatchObject({ description: 'oauth handler', prompt: 'Add oauth to src/api/a.py' });

    const ok = await $.tool.call(byAgent(agent.agentId));
    expect(ok.deny).toBeUndefined();
    const core = await $.tool.call(byAgent(agent.agentId, '/proj/src/core/db.py'));
    expect(core.deny).toContain('haiku may not write src/core/db.py');

    await $.turn.complete(DONE);
    expect(seen.outcomes.at(-1)).toMatchObject({ spawned: 1, denials: 3 });
  });

  test('on: forks keep their parent model and are not routed', { options: { jev_router_mode: 'on' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    await $.agent.spawn(spawn('look around', 'fork', true));
    expect(seen.modes).not.toContain('spawn');
    expect(seen.spawned.at(-1)?.model).toBeUndefined();
  });

  test('on: repeated errors move the next subagent for those files up', { options: { jev_router_mode: 'on' } }, async ($, on) => {
    const seen = engine(on, true);
    await $.session.start(START);
    await $.turn.start({ text: 'fix a', turnId: 't1' });
    const agent = await $.agent.spawn(spawn('Fix src/api/a.py', 'fix a'));
    for (let i = 0; i < 3; i++) await $.tool.call(byAgent(agent.agentId));
    await $.agent.spawn(spawn('Fix src/api/a.py again', 'fix a again'));
    expect(seen.requests.at(-1)).toMatchObject({ escalated: { 'src/api/a.py': 1 } });
  });

  test('off: no section, no gate, spawns untouched', { options: { jev_router_mode: 'off' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    await $.turn.start({ text: 'add oauth', turnId: 't1' });
    expect((await $.tool.call(EDIT)).deny).toBeUndefined();
    await $.agent.spawn(spawn('Add oauth to src/api/a.py', 'oauth'));
    expect(seen.spawned.at(-1)?.model).toBeUndefined();
    expect(seen.modes).toEqual(['render']);
  });

  test('a shell command that deletes is a write; one that reads is not', async () => {
    expect(deletedPaths('rm -rf build/ && ls')).toEqual(['build/']);
    expect(deletedPaths('git rm "src/old file.py"; git status')).toEqual(['src/old file.py']);
    expect(deletedPaths('mv a.py b.py')).toEqual(['a.py']);
    expect(deletedPaths('Remove-Item -Recurse dist')).toEqual(['dist']);
    expect(deletedPaths('cat a.py | grep rm')).toEqual([]);
  });

  test('a path takes its nearest listed ancestor rule', async () => {
    const tiers = ['haiku', 'sonnet', 'opus'];
    expect(lookup(RENDER.rules, 'src/core/db/models.py', tiers).write).toEqual(['opus']);
    expect(lookup(RENDER.rules, 'SRC/Gen/pb.py', tiers).write).toEqual([]);
    expect(lookup(RENDER.rules, 'docs/a.md', tiers).write).toEqual(tiers);
    expect(relPath('C:\\proj\\src\\a.py', 'C:\\proj')).toBe('src/a.py');
  });
});
