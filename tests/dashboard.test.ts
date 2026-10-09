import type { AgentSpawnInput, On } from 'claude-code';
import { describe, expect, test } from 'claude-code/testing';
import {
  compacterText,
  DASHBOARD_STAR_SPACING,
  dashboardStarFrame,
  dashboardStarPoints,
  routerText,
  skillsText,
  type DashboardView,
} from '../hooks/dashboard';

const RENDER = {
  section: '## optim-jev model router',
  rules: {},
  tiers: ['haiku', 'sonnet', 'opus'],
  current: 'sonnet',
  has_rules: true,
};

const INDEX = { count: 7, dirs: ['C:/Users/me/.claude/skills'], names: ['hallmark', 'deploy'] };
const SHORTLIST = {
  picks: ['hallmark', 'deploy'],
  context: 'optim-jev skill picker shortlisted hallmark and deploy',
  failed: null,
};
const SPAWN = {
  model: 'haiku',
  files: ['docs/getting-started.md'],
  appendix: '',
  toast: 'jev · update docs → haiku',
  source: 'rules',
  escalated: 0,
  jev_failed: null,
};
const COMPACT = {
  action: 'defer',
  message: 'jev-compacter: deferred ~14k tokens',
  log: [],
  freedTokensEst: 14_000,
};
type EngineSettings = {
  contextPercent?: number;
  compactAnswer?: Record<string, unknown>;
  builtinTokensAfter?: number;
  storedDashboard?: Record<string, unknown>;
};

const START = { cwd: '/proj', surface: 'desktop', isInteractive: true } as const;
const BAND = {
  plugin: 'optim-jev',
  surface: 'desktop',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 120,
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as never;
const TERMINAL_BAND = {
  plugin: 'optim-jev',
  surface: 'terminal',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 5,
    bodyColumns: 168,
    scroll: { offset: 0, bodyRows: 5 },
    view: {},
  },
} as never;

function engine(on: On, settings: EngineSettings = {}) {
  const store = new Map<string, unknown>();
  if (settings.storedDashboard) store.set('optim_jev_dashboard_session', settings.storedDashboard);
  const seen = { commands: [] as string[], modes: [] as string[], statuses: [] as (string | undefined)[], store };
  const percent = settings.contextPercent ?? 42;
  on('session.id', () => ({ value: 'sid-dashboard' }));
  on('session.root', () => ({ value: '/proj' }));
  on('session.model', () => ({ value: 'claude-sonnet-5-5' }));
  on('session.messages', () => ({ value: [] }));
  on('session.usage', () => ({
    value: { context: { tokens: percent * 2_000, window: 200_000, percent } },
  }));
  on('store.get', (_$, e) => ({ value: store.get(e.key) }));
  on('store.set', (_$, e) => {
    store.set(e.key, e.value);
    return { value: undefined };
  });
  on('env.get', () => ({ value: undefined }));
  on('settings.read', () => ({ value: {} }));
  on('tool.list', () => ({ value: [{ name: 'ListSkills', description: '' }] }));
  on('command.register', (_$, e) => ({ value: { command: e.name } }));
  on('command.run', (_$, e) => {
    seen.commands.push(`${e.command} ${e.args}`.trim());
    return { text: 'ok' };
  });
  on('ui.status', (_$, e) => {
    seen.statuses.push(e.text);
    return { value: undefined };
  });
  on('ui.invalidate', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
  on('session.start', (_$, e) => ({ cwd: e.cwd }));
  on('session.compact', (_$, e) => ({
    messages: e.messages ?? [],
    tokensBefore: percent * 2_000,
    tokensAfter: settings.builtinTokensAfter ?? 20_000,
  }));
  on('prompt.submit', (_$, e) => ({ text: e.text, context: e.context }));
  on('agent.spawn', (_$, e) => ({ model: e.model ?? 'claude-sonnet-5-5', agentId: 'agent-1' }));
  on('process.run', (_$, e) => {
    const mode = e.argv[3] ?? '';
    seen.modes.push(mode);
    const answers: Record<string, unknown> = {
      render: RENDER,
      index: INDEX,
      shortlist: SHORTLIST,
      spawn: SPAWN,
      compact: settings.compactAnswer ?? COMPACT,
    };
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
  return seen;
}

function view(overrides: Partial<DashboardView> = {}): DashboardView {
  return {
    contextPercent: 42,
    activity: null,
    compacter: {
      enabled: true,
      softPercent: 60,
      hardPercent: 85,
      outcome: { kind: 'applied', freedTokensEst: 12_400 },
      degraded: false,
    },
    router: {
      mode: 'on',
      routing: false,
      offline: false,
      hasRules: true,
      decision: { task: 'update docs', model: 'haiku', source: 'rules', escalated: 0 },
    },
    skills: {
      mode: 'on',
      scope: 'global',
      count: 7,
      indexing: false,
      picking: false,
      outcome: { kind: 'picked', picks: ['hallmark', 'deploy'] },
    },
    ...overrides,
  };
}

function spawn(): AgentSpawnInput {
  return {
    tool_use_id: 'toolu_dashboard',
    prompt: 'Update docs/getting-started.md',
    description: 'update docs',
    subagentType: 'general-purpose',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'claude-sonnet-5-5',
    background: false,
    fork: false,
  };
}

describe('optim-jev dashboard', () => {
  test('formatters preserve the useful facts in wide and narrow layouts', () => {
    const state = view();
    expect(compacterText(state)).toContain('Context 42% · soft 60% · hard 85% · freed ~12k');
    expect(routerText(state)).toContain('update docs → Haiku via rules');
    expect(skillsText(state)).toContain('Skills Global 7 · hallmark +1');
    expect(compacterText(state, true)).toContain('Context 42% · soft 60% · hard 85%');
    expect(routerText(state, true)).toBe('Router on → Haiku');
    expect(skillsText(state, true)).toContain('Skills Global 7');
  });

  test('star particles are deterministic and twinkle between frames', () => {
    const first = dashboardStarPoints(126, 3, 0);
    const later = dashboardStarPoints(126, 3, 80);
    expect(first).toHaveLength(12);
    expect(first.map(({ x }) => Math.floor(x / DASHBOARD_STAR_SPACING))).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    expect(first.map(({ x, y }) => `${x}:${y}`)).not.toEqual(later.map(({ x, y }) => `${x}:${y}`));
    expect(dashboardStarFrame(0)).toBe(dashboardStarFrame(0));
    expect(dashboardStarFrame(0)).not.toBe(dashboardStarFrame(6));
  });

  test('formatters name the fail-open fallback instead of a generic error', () => {
    expect(routerText(view({ router: { mode: 'on', routing: false, offline: false, hasRules: false, decision: null } }))).toContain(
      'no rules · run /jev-route init',
    );
    expect(
      routerText(
        view({
          router: {
            mode: 'on',
            routing: false,
            offline: true,
            hasRules: true,
            decision: { task: 'tests', model: 'sonnet', source: 'fallback', escalated: 0 },
          },
        }),
      ),
    ).toContain('session model · Jev offline');
    expect(
      skillsText(
        view({
          skills: {
            mode: 'on',
            scope: 'project',
            count: 7,
            indexing: false,
            picking: false,
            outcome: { kind: 'jev_offline', picks: ['hallmark'] },
          },
        }),
      ),
    ).toContain('Jev offline · skill names attached');
    expect(
      skillsText(
        view({
          skills: {
            mode: 'on',
            scope: 'project',
            count: 7,
            indexing: false,
            picking: false,
            outcome: { kind: 'unavailable', picks: [] },
          },
        }),
      ),
    ).toContain('picker unavailable');
    expect(
      compacterText(
        view({
          compacter: {
            enabled: true,
            softPercent: 60,
            hardPercent: 85,
            outcome: { kind: 'builtin' },
            degraded: true,
          },
        }),
      ),
    ).toContain('built-in summary');
  });

  test(
    'shows live feature state and reuses the existing controls',
    { options: { jev_dashboard_mode: 'on', jev_router_mode: 'on', jev_skills_mode: 'on', jev_skills_scope: 'global' } },
    async ($, on) => {
      const seen = engine(on);
      await $.session.start(START);
      await $.prompt.submit({
        text: 'Design a polished dashboard for this project',
        origin: { kind: 'composer' },
        wait: false,
      });
      await $.agent.spawn(spawn());

      const beforeRender = seen.modes.slice();
      const band = await $.ui.mount(BAND);
      expect(seen.modes).toEqual(beforeRender);
      const text = JSON.stringify(await band.drawn());
      expect(text).toContain('Context 42%');
      expect(text).toContain('update docs → Haiku via rules');
      expect(text).toContain('Skills Global 7 · hallmark +1');

      await band.press({ key: 'dashboard-router' });
      await band.redraw();
      expect(JSON.stringify(await band.drawn())).toContain('Router off');
      await band.press({ key: 'dashboard-skills' });
      await band.redraw();
      expect(JSON.stringify(await band.drawn())).toContain('Skills off');
      await band.press({ key: 'dashboard-compact' });
      expect(seen.commands).toContain('compact');
      await band.unmount();
    },
  );

  test('shows the latest compaction outcome', { options: { jev_dashboard_mode: 'on' } }, async ($, on) => {
    engine(on);
    await $.session.start(START);
    await $.session.compact({});
    const band = await $.ui.mount(BAND);
    expect(JSON.stringify(await band.drawn())).toContain('deferred ~14k');
    await band.unmount();
  });

  test('built-in compaction updates context from its exact tokensAfter', { options: { jev_dashboard_mode: 'on' } }, async ($, on) => {
    const seen = engine(on, {
      compactAnswer: { action: 'summarize', message: 'use built-in summary', log: [], freedTokensEst: 0 },
      builtinTokensAfter: 20_000,
    });
    await $.session.start(START);
    await $.session.compact({
      messages: [{ role: 'assistant', text: 'summary', toolUses: [] }],
    } as never);
    const band = await $.ui.mount(BAND);
    const text = JSON.stringify(await band.drawn());
    expect(text).toContain('Context 10%');
    expect(text).toContain('built-in summary');
    await Promise.resolve();
    expect(seen.store.get('optim_jev_dashboard_session')).toMatchObject({
      contextPercent: 10,
      compactionOutcome: { kind: 'builtin' },
    });
    await band.unmount();
  });

  test(
    'resumed session restores the latest dashboard snapshot instead of replacing it with startup zero',
    { options: { jev_dashboard_mode: 'on', jev_router_mode: 'on', jev_skills_mode: 'on', jev_skills_scope: 'global' } },
    async ($, on) => {
      engine(on, {
        contextPercent: 0,
        storedDashboard: {
          sessionId: 'sid-dashboard',
          contextPercent: 27,
          compactionOutcome: { kind: 'applied', freedTokensEst: 12_000 },
          compacterDegraded: false,
          routerDecision: { task: 'restore docs', model: 'haiku', source: 'rules', escalated: 0 },
          routerOffline: false,
          skillsOutcome: { kind: 'picked', picks: ['hallmark', 'deploy'] },
        },
      });
      await $.session.start(START);
      const band = await $.ui.mount(BAND);
      const text = JSON.stringify(await band.drawn());
      expect(text).toContain('Context 27%');
      expect(text).toContain('freed ~12k');
      expect(text).toContain('restore docs → Haiku via rules');
      expect(text).toContain('hallmark +1');
      await band.unmount();
    },
  );

  test('terminal uses full feature names on separate readable rows', { options: { jev_dashboard_mode: 'on' } }, async ($, on) => {
    engine(on);
    await $.session.start(START);
    const band = await $.ui.mount(TERMINAL_BAND);
    const text = JSON.stringify(await band.drawn());
    expect(text).toContain('✦ optim-jev');
    expect((text.match(/✦/g) ?? [])).toHaveLength(1);
    expect(text).toContain('Context 42% · soft 60% · hard 85%');
    expect(text).toContain('Router off');
    expect(text).toContain('Skills off');
    expect(text).toContain('Enable router');
    expect(text).toContain('Enable skills');
    expect(text).toContain('dashboard-stars');
    expect(text).toContain('"position":"absolute"');
    expect(text).toContain('"columns":164');
    expect(text).not.toContain('│');
    expect(text).not.toContain('dashboard-actions');
    expect(text.indexOf('Context 42%')).toBeLessThan(text.indexOf('Router off'));
    expect(text.indexOf('Router off')).toBeLessThan(text.indexOf('Skills off'));
    await band.unmount();
  });

  test('dashboard off keeps the existing status-only behavior', { options: { jev_dashboard_mode: 'off' } }, async ($, on) => {
    const seen = engine(on);
    await $.session.start(START);
    expect(seen.statuses.at(-1)).toContain('◆ jev · compact on · router off · skills off');
  });
});
