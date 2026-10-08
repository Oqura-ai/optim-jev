import type { On } from 'claude-code';
import { describe, expect, test } from 'claude-code/testing';

const SHORTLIST = { picks: ['deploy'], context: 'optim-jev skill picker (Jev) shortlisted these skills…\n- deploy (80%): Ship it', failed: null };
const INDEX = { count: 4, dirs: ['C:/Users/me/.claude/skills/pptx'], names: ['deploy', 'pptx'] };

function engine(on: On) {
  const seen = { modes: [] as string[], loaded: [] as Record<string, unknown>[] };
  on('session.id', () => ({ value: 'sid-1' }));
  on('session.root', () => ({ value: '/proj' }));
  on('session.model', () => ({ value: 'claude-sonnet-5-5' }));
  on('session.messages', () => ({ value: [] }));
  on('store.get', () => ({ value: undefined }));
  on('store.set', () => ({ value: undefined }));
  on('env.get', () => ({ value: undefined }));
  on('settings.read', () => ({ value: {} }));
  on('tool.list', () => ({ value: [{ name: 'ListSkills', description: '' }] }));
  on('command.register', (_$, e) => ({ value: { command: e.name } }));
  on('ui.status', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
  on('session.start', (_$, e) => ({ cwd: e.cwd }));
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }));
  on('prompt.attachment', (_$, e) => ({ text: e.text }));
  on('tool.check', () => ({ decision: 'ask' }));
  on('skill.prompt', (_$, e) => ({ text: e.text }));
  on('process.run', (_$, e) => {
    const mode = e.argv[3] ?? '';
    seen.modes.push(mode);
    if (mode === 'loaded') seen.loaded.push(JSON.parse(e.init?.stdin ?? '{}'));
    const answers: Record<string, unknown> = { index: INDEX, shortlist: SHORTLIST, render: { section: '', rules: {}, tiers: [], current: null, has_rules: false } };
    return { value: { exitCode: 0, stdout: JSON.stringify(answers[mode] ?? {}), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } };
  });
  return seen;
}

const START = { cwd: '/proj', surface: null, isInteractive: false } as const;
const prompt = (text: string) => ({ text, origin: { kind: 'composer' }, wait: false }) as const;
const LISTING = { type: 'skill_listing', text: '- deploy: Ship it\n- pptx: Build decks', origin: { kind: 'engine' } } as const;

describe('jev-skills', () => {
  test('on: the listing is replaced, a prompt gets its shortlist, a load is logged', { options: { jev_skills_mode: 'on' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    const listing = await $.prompt.attachment(LISTING);
    expect(listing.text).toContain('ListSkills');
    expect(listing.text).not.toContain('pptx');

    const submitted = await $.prompt.submit(prompt('deploy the release to staging'));
    expect(submitted.context?.at(-1)).toContain('deploy (80%)');

    const short = await $.prompt.submit(prompt('yes'));
    expect(short.context ?? []).toEqual([]);
    expect(seen.modes.filter((m) => m === 'shortlist').length).toBe(1);

    await $.skill.prompt({ skill: 'deploy', text: 'body' });
    expect(seen.loaded.at(-1)).toMatchObject({ skill: 'deploy', shortlisted: true });
  });

  test('global: reads inside an indexed skill folder are allowed, others still ask', { options: { jev_skills_mode: 'on', jev_skills_scope: 'global' } }, async ($, on) => {
    engine(on);
    await $.session.start(START);
    expect((await $.tool.check({ tool: 'Read', input: { file_path: 'C:\\Users\\me\\.claude\\skills\\pptx\\SKILL.md' } })).decision).toBe('allow');
    expect((await $.tool.check({ tool: 'Read', input: { file_path: 'C:\\Users\\me\\secrets.txt' } })).decision).toBe('ask');
  });

  test('project scope grants no reads outside the project', { options: { jev_skills_mode: 'on' } }, async ($, on) => {
    engine(on);
    await $.session.start(START);
    expect((await $.tool.check({ tool: 'Read', input: { file_path: 'C:/Users/me/.claude/skills/pptx/SKILL.md' } })).decision).toBe('ask');
  });

  test('off: the listing stays and no Jev call is made', { options: { jev_skills_mode: 'off' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    expect((await $.prompt.attachment(LISTING)).text).toContain('pptx');
    await $.prompt.submit(prompt('deploy the release to staging'));
    expect(seen.modes).not.toContain('shortlist');
  });
});
