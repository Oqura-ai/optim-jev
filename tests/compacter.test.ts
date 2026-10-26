import type { On } from 'claude-code';
import { describe, expect, mock, test } from 'claude-code/testing';
import type { Engine } from 'claude-code/testing';

const MINUTE = 60_000;
const START = { cwd: '/proj', surface: 'terminal', isInteractive: true } as const;
const DONE = { turnId: 't1', answer: 'done', durationMs: 1, isAborted: false, reason: 'answer' } as const;
const MESSAGES = [{ role: 'user', text: 'fix it', toolUses: [] }];
const APPLIED = {
  action: 'apply',
  message: 'jev-compacter: freed ~3k tokens',
  log: [],
  freedTokensEst: 3_000,
  messages: [{ from: 0 }],
  tokensAfter: 97_000,
};

type EngineOptions = {
  /** What Python's `check` answers. */
  level?: string | null;
  /** The label the person picks in the dialog. */
  answer?: string;
  rateLimits?: { kind: string; percentUsed: number }[];
};

/** Stands in for the engine and the Python child; records what reached them. */
function engine(top: Engine, on: On, options: EngineOptions = {}) {
  const seen = {
    checks: [] as { usage: Record<string, unknown>; options: Record<string, unknown> }[],
    compacts: [] as { level: string; usage: Record<string, unknown>; options: Record<string, unknown> }[],
    questions: [] as string[],
    commands: [] as string[],
    builtin: 0,
  };
  const clock = mock.clock(on);
  on('session.id', () => ({ value: 'sid-cold' }));
  on('session.root', () => ({ value: '/proj' }));
  on('session.model', () => ({ value: 'claude-sonnet-5-5' }));
  on('session.messages', () => ({ value: MESSAGES as never }));
  on('session.usage', () => ({
    value: { startedAt: 0, context: { tokens: 100_000, window: 200_000, percent: 50 }, rateLimits: options.rateLimits ?? [] },
  }));
  on('store.get', () => ({ value: undefined }));
  on('store.set', () => ({ value: undefined }));
  on('env.get', () => ({ value: undefined }));
  on('settings.read', () => ({ value: {} }) as never);
  on('tool.list', () => ({ value: [] }));
  on('command.register', (_$, e) => ({ value: { command: e.name } }));
  on('ui.status', () => ({ value: undefined }));
  on('ui.invalidate', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
  on('session.start', (_$, e) => ({ cwd: e.cwd }));
  on('classic.SessionStart', () => ({ value: {} }) as never);
  on('classic.PostModelSwitch', () => ({ value: {} }) as never);
  on('turn.start', (_$, e) => ({ turnId: e.turnId }));
  on('turn.complete', (_$, e) => ({ text: e.answer }));
  // Core's /compact: a compaction every plugin's session.compact hook sees.
  on('command.run', async (_$, e) => {
    seen.commands.push(e.command);
    if (e.command === 'compact') await top.session.compact({ trigger: 'manual', messages: MESSAGES } as never);
    return { text: '' };
  });
  on('session.compact', () => {
    seen.builtin += 1;
    return { messages: MESSAGES as never, tokensBefore: 100_000, tokensAfter: 20_000 };
  });
  on('tool.call', { tool: 'AskUserQuestion' }, (_$, e) => {
    const { questions } = e as unknown as { questions: { question: string }[] };
    const question = questions[0]?.question ?? '';
    seen.questions.push(question);
    return { result: { questions, answers: { [question]: options.answer ?? 'Not now' } } } as never;
  });
  on('process.run', (_$, e) => {
    const mode = e.argv[3] ?? '';
    const request = JSON.parse(e.init?.stdin ?? '{}');
    if (mode === 'check') seen.checks.push(request);
    if (mode === 'compact') seen.compacts.push(request);
    const answers: Record<string, unknown> = {
      check: { level: options.level === undefined ? 'idle' : options.level },
      compact: APPLIED,
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
  return { seen, clock };
}

const AUTO_5M = { jev_compacter_cold_cache: 'auto', jev_compacter_cache_ttl: '5m', jev_dashboard_mode: 'off' };
const ASK_5M = { jev_compacter_cache_ttl: '5m', jev_dashboard_mode: 'off' };
const QUIET = { jev_compacter_cold_cache: 'off', jev_dashboard_mode: 'off' };

describe('jev-compacter cold cache', () => {
  test('auto: once the TTL passes idle, a Jev prune runs once with the cache marked cold', { options: AUTO_5M }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(5 * MINUTE);
    expect(seen.checks).toHaveLength(0);
    await clock.advance(MINUTE);
    expect(seen.checks).toHaveLength(1);
    expect(seen.checks[0]?.usage.cache_cold).toBe(true);
    expect(seen.compacts.map((c) => c.level)).toEqual(['idle']);
    expect(seen.compacts[0]?.usage.cache_cold).toBe(true);
    expect(seen.builtin).toBe(0);
    expect(seen.commands).toEqual(['compact']);
    await clock.advance(120 * MINUTE);
    expect(seen.checks).toHaveLength(1);
  });

  test('a new turn before the TTL keeps the cache warm and cancels the check', { options: AUTO_5M }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(4 * MINUTE);
    await $.turn.start({ text: 'and this', turnId: 't2' });
    await clock.advance(10 * MINUTE);
    expect(seen.checks).toHaveLength(0);
  });

  test('Python decides: no level, no prune', { options: AUTO_5M }, async ($, on) => {
    const { seen, clock } = engine($, on, { level: null });
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(6 * MINUTE);
    expect(seen.checks).toHaveLength(1);
    expect(seen.compacts).toHaveLength(0);
  });

  test('ask: "Not now" leaves the conversation alone', { options: ASK_5M }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(6 * MINUTE);
    expect(seen.questions).toHaveLength(1);
    expect(seen.questions[0]).toContain('50% full');
    expect(seen.compacts).toHaveLength(0);
  });

  test('ask: "Prune now" runs the Jev prune, never the built-in summary', { options: ASK_5M }, async ($, on) => {
    const { seen, clock } = engine($, on, { answer: 'Prune now' });
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(6 * MINUTE);
    expect(seen.compacts.map((c) => c.level)).toEqual(['idle']);
    expect(seen.builtin).toBe(0);
  });

  test('a person\'s own /compact is still manual', { options: ASK_5M }, async ($, on) => {
    const { seen } = engine($, on);
    await $.session.start(START);
    await $.session.compact({ trigger: 'manual', messages: MESSAGES } as never);
    expect(seen.compacts.map((c) => c.level)).toEqual(['manual']);
  });

  test('a subscription within its plan usage gets the one-hour TTL', { options: { jev_compacter_cold_cache: 'auto' } }, async ($, on) => {
    const { seen, clock } = engine($, on, { rateLimits: [{ kind: 'five_hour', percentUsed: 12 }] });
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(30 * MINUTE);
    expect(seen.checks).toHaveLength(0);
    await clock.advance(31 * MINUTE);
    expect(seen.checks).toHaveLength(1);
  });

  test('past the plan limit, or with an API key, the TTL is five minutes', { options: { jev_compacter_cold_cache: 'auto' } }, async ($, on) => {
    const { seen, clock } = engine($, on, { rateLimits: [{ kind: 'five_hour', percentUsed: 100 }] });
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(6 * MINUTE);
    expect(seen.checks).toHaveLength(1);
  });

  test('a resume past the TTL is checked right away', { options: { jev_compacter_cold_cache: 'auto' } }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.classic.SessionStart({ source: 'resume', prompt_cache_likely_expired: true, seconds_since_last_response: 7_200 });
    await clock.advance(5_000);
    expect(seen.checks).toHaveLength(1);
    expect(seen.checks[0]?.usage.cache_cold).toBe(true);
  });

  test('a model switch is checked right away', { options: { jev_compacter_cold_cache: 'auto' } }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.turn.complete(DONE);
    await $.classic.PostModelSwitch({
      from_model: 'claude-sonnet-5-5', to_model: 'claude-opus-5-5', requested_model: 'opus', source: 'command',
      context_tokens: 100_000, prompt_cache_warm: true, cache_ttl: '1h', estimated_cache_write_usd: 1, pricing: 'catalog',
    });
    await clock.advance(5_000);
    expect(seen.checks).toHaveLength(1);
  });

  test('off asks nothing and runs nothing', { options: { ...AUTO_5M, jev_compacter_cold_cache: 'off' } }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start(START);
    await $.turn.complete(DONE);
    await clock.advance(10 * MINUTE);
    expect(seen.checks).toHaveLength(0);
  });

  test('save-tokens prunes from 50% and hands Python its numbers', { options: { ...QUIET, jev_compacter_preset: 'save-tokens' } }, async ($, on) => {
    const { seen } = engine($, on, { level: null });
    await $.session.start(START);
    await $.turn.complete(DONE);
    expect(seen.checks).toHaveLength(1);
    expect(seen.checks[0]?.options).toMatchObject({
      jev_compacter_soft_percent: 50, jev_compacter_keep_threshold: 0.6, jev_compacter_min_freed_tokens: 4_000,
    });
  });

  test('a number the person set beats the style', {
    options: { ...QUIET, jev_compacter_preset: 'save-tokens', jev_compacter_soft_percent: 70, jev_compacter_keep_threshold: 0.4 },
  }, async ($, on) => {
    const { seen } = engine($, on, { level: null });
    await $.session.start(START);
    await $.turn.complete(DONE);
    expect(seen.checks).toHaveLength(0);
    await $.session.compact({ trigger: 'manual', messages: MESSAGES } as never);
    expect(seen.compacts[0]?.options).toMatchObject({ jev_compacter_soft_percent: 70, jev_compacter_keep_threshold: 0.4 });
  });

  test('a non-interactive run sets no timer', { options: ASK_5M }, async ($, on) => {
    const { seen, clock } = engine($, on);
    await $.session.start({ ...START, surface: null, isInteractive: false });
    await $.turn.complete(DONE);
    await clock.advance(10 * MINUTE);
    expect(seen.checks).toHaveLength(0);
    expect(seen.questions).toHaveLength(0);
  });
});
