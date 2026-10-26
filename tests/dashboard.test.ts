import type { AgentSpawnInput, On } from 'claude-code';
import { describe, expect, test } from 'claude-code/testing';
import {
  compacterText,
  dashboardLayout,
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
    value: { startedAt: 0, context: { tokens: percent * 2_000, window: 200_000, percent }, rateLimits: [] },
  }));
  on('store.get', (_$, e) => ({ value: store.get(e.key) }));
  on('store.set', (_$, e) => {
    store.set(e.key, e.value);
    return { value: undefined };
  });
  on('env.get', () => ({ value: undefined }));
  on('settings.read', () => ({ value: {} }));
  on('tool.list', () => ({ value: [{ name: 'ListSkills', description: '', mcp: false }] }));
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
  test('diagnostic command output uses an uncolored metric table', { options: {} }, async ($, on) => {
    engine(on);
    const output = await $.ui.mount({
      plugin: 'optim-jev', surface: 'terminal', component: 'CommandOutput',
      props: {
        command: 'jev-route', args: 'stats',
        text: 'Routed subagents: 3 · haiku 67% · sonnet 33%\n  net saved   $1.25',
        isErrored: false,
      },
    } as never);
    const text = JSON.stringify(await output.drawn());
    expect(text).toContain('Router stats');
    expect(text).toContain('"width":18');
    expect(text).not.toContain('"color"');
    expect(text).not.toContain('borderStyle');
    await output.unmount();
  });

  test('layout respects height as well as width, including zero space', () => {
    for (const columns of [0, 1, 20, 49, 50, 59, 60, 80, 120, 168]) {
      for (const rows of [0, 1, 2, 3, 4, 5, 10]) {
        const layout = dashboardLayout(columns, rows);
        expect(layout.full).toBe(columns >= 60 && rows >= 5);
        expect(layout.controls).toBe(columns >= 50 && rows >= 2);
        expect(layout.width).toBe(columns);
        expect(layout.rows).toBe(rows);
      }
    }
    expect(dashboardLayout(Number.NaN, Number.POSITIVE_INFINITY)).toMatchObject({ width: 0, rows: 0, full: false });
    expect(dashboardLayout(-1, -1)).toMatchObject({ width: 0, rows: 0, full: false });
  });

  test('terminal render stays valid at the width and height breakpoints', { options: { jev_dashboard_mode: 'on' } }, async ($, on) => {
    engine(on);
    await $.session.start(START);
    for (const columns of [1, 49, 50, 59, 60, 120]) {
      for (const rows of [1, 2, 4, 5]) {
        const band = await $.ui.mount({
          plugin: 'optim-jev', surface: 'terminal', component: 'AbovePrompt',
          props: { hasSurvey: false, isWorking: false, maxRows: rows, bodyColumns: columns,
            scroll: { offset: 0, bodyRows: rows }, view: {} },
        } as never);
        const text = JSON.stringify(await band.drawn());
        const layout = dashboardLayout(columns, rows);
        expect(text).toContain('42%');
        expect(text.includes('borderStyle')).toBe(layout.full);
        expect(text.includes('dashboard-stars')).toBe(layout.full);
        expect(text.includes('dashboard-compact')).toBe(layout.full || layout.controls);
        expect(text.includes('dashboard-router')).toBe(layout.full || layout.controls);
        expect(text.includes('dashboard-skills')).toBe(layout.full || layout.controls);
        if (!layout.full) {
          expect(text).toContain(`"height":${layout.controls ? 2 : 1}`);
          expect(text).toContain(`"width":${columns}`);
          expect(text).toContain('"wrap":"truncate"');
        }
        await band.unmount();
      }
    }
  });

  test('formatters keep the useful facts, and name each fallback', () => {
    const state = view();
    expect(compacterText(state)).toContain('Context 42% · soft 60% · hard 85% · freed ~12k');
    expect(routerText(state)).toContain('update docs → Haiku via rules');
    expect(skillsText(state)).toContain('Skills Global 7 · hallmark +1');
    expect(routerText(state, true)).toBe('Router on → Haiku');

    const compacter = (outcome: DashboardView['compacter']['outcome']) => compacterText(view({ compacter: { ...state.compacter, outcome } }));
    const router = (patch: Partial<DashboardView['router']>) => routerText(view({ router: { ...state.router, ...patch } }));
    const skills = (outcome: DashboardView['skills']['outcome']) => skillsText(view({ skills: { ...state.skills, outcome } }));
    expect(compacter({ kind: 'deferred', freedTokensEst: 14_000 })).toContain('deferred ~14k');
    expect(compacter({ kind: 'builtin' })).toContain('built-in summary');
    expect(router({ hasRules: false, decision: null })).toContain('no rules · run /jev-route init');
    expect(router({ offline: true, decision: { task: 'tests', model: 'sonnet', source: 'fallback', escalated: 0 } })).toContain(
      'session model · Jev offline',
    );
    expect(skills({ kind: 'jev_offline', picks: ['hallmark'] })).toContain('Jev offline · skill names attached');
    expect(skills({ kind: 'unavailable', picks: [] })).toContain('picker unavailable');
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
