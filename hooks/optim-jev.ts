import type {
  AgentSpawnInput,
  CommandRunInput,
  CommandRunResult,
  EngineInterface as Engine,
  ModelUsage,
  On,
  PluginOptions,
  PromptComposeSection,
  PromptSubmitInput,
  Register,
  SessionCompactInput,
  SessionCompactResult,
  SessionMessage,
  TurnCompleteInput,
} from 'claude-code';
import type { Mode, Permission, RenderAnswer, SessionRecord, SpawnAnswer } from './router-lib';
import {
  DEFAULT_ESCALATE_AFTER,
  DEFAULT_INIT_MODEL,
  MODEL_GONE,
  MODES,
  ROUTER_COMMAND,
  ROUTER_MODULE,
  SECTION_ID,
  STORE_KEY,
  USAGE,
  lookup,
  newTurn,
  numberOption,
  oneOf,
  relPath,
  writeTargets,
} from './router-lib';

type Level = 'soft' | 'hard' | 'idle' | 'manual';

type KeptMessage = {
  from: number;
  toolUses?: { tool_use_id: string; text?: string }[];
  toolResults?: { tool_use_id: string; text: string }[];
};

type CompactAnswer = {
  action: 'skip' | 'apply' | 'defer' | 'summarize';
  message: string;
  log: string[];
  messages?: KeptMessage[];
  tokensAfter?: number;
};

type CheckAnswer = { level: Level | null };

const API_KEY_OPTION = 'typesafe_api_key';
const PYTHON_TIMEOUT_MS = 180_000;

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function notify($: Engine, text: string, timeoutMs = 15_000): void {
  $.ui.log(text);
  $.ui.toast(text, { timeoutMs });
}

async function apiKey($: Engine, options: PluginOptions): Promise<string | undefined> {
  const configured = options[API_KEY_OPTION];
  if (typeof configured === 'string' && configured) return configured;
  const fromEnv = await $.env.get('TYPESAFE_API_KEY');
  if (fromEnv) return fromEnv;
  const env = (await $.settings.read())['env'];
  const fromSettings =
    env && typeof env === 'object' ? (env as Record<string, unknown>)['TYPESAFE_API_KEY'] : undefined;
  return typeof fromSettings === 'string' && fromSettings ? fromSettings : undefined;
}

/** Options for the Python tools, the secret left out (it travels in the child's environment). */
function toolOptions(options: PluginOptions): Record<string, unknown> {
  const { [API_KEY_OPTION]: _secret, ...rest } = options as Record<string, unknown>;
  return rest;
}

async function runTool<T>(
  $: Engine,
  options: PluginOptions,
  module: string,
  mode: string,
  request: object,
  timeoutMs = PYTHON_TIMEOUT_MS,
): Promise<T> {
  const python = typeof options['python'] === 'string' && options['python'] ? options['python'] : 'python';
  const env: Record<string, string> = { PYTHONPATH: `${$.plugin.root}/src`, PYTHONIOENCODING: 'utf-8' };
  const key = await apiKey($, options);
  if (key) env['TYPESAFE_API_KEY'] = key;
  const { exitCode, stdout, stderr } = await $.process.run([python, '-m', module, mode], {
    env,
    stdin: JSON.stringify(request),
    timeoutMs,
  });
  if (exitCode !== 0) {
    throw new Error(`${python} exited ${exitCode}: ${stderr.trim().split('\n').slice(-3).join(' | ')}`);
  }
  return JSON.parse(stdout) as T;
}

// ------------------------------------------------------------- usage log

const LOGS_MODULE = 'optim_jev.core.logs';
// Claude's own token counts, as the API reported them; written to logs/claude/<session_id>.jsonl
// in one Python call when a main-loop turn ends (the hook API can't append to a file).
let usageBuffer: Record<string, unknown>[] = [];

function recordUsage(kind: string, usage: ModelUsage, fields: Record<string, unknown>): void {
  usageBuffer.push({
    ts: Math.round(Date.now() / 1000),
    kind,
    ...fields,
    input_tokens: usage.input_tokens,
    output_tokens: usage.output_tokens,
    cache_read_input_tokens: usage.cache_read_input_tokens,
    cache_creation_input_tokens: usage.cache_creation_input_tokens,
  });
}

async function flushUsage($: Engine, options: PluginOptions): Promise<void> {
  if (usageBuffer.length === 0) return;
  const records = usageBuffer;
  usageBuffer = [];
  try {
    await runTool($, options, LOGS_MODULE, 'claude', {
      session_id: await $.session.id(),
      project_dir: await $.session.root(),
      records,
    });
  } catch (error) {
    $.ui.log(`optim-jev: usage not logged (${errorText(error)})`, { to: 'debug' });
  }
}

const TOOL_MODULE = 'optim_jev.tools.jev_compacter.tool';
const DEFAULT_SOFT_PERCENT = 60;

async function sessionFields($: Engine, options: PluginOptions) {
  const { context } = await $.session.usage();
  const used = context.tokens ?? Math.round(((context.percent ?? 0) / 100) * context.window);
  return {
    session_id: await $.session.id(),
    project_dir: await $.session.root(),
    usage: { used_tokens: used, window_tokens: context.window, idle_seconds: 0 },
    options: toolOptions(options),
    percent: context.percent ?? (100 * used) / context.window,
  };
}

function wire(message: SessionMessage) {
  return {
    role: message.role,
    text: message.text,
    toolUses: message.toolUses.map((t) => ({
      tool_use_id: t.tool_use_id,
      tool: t.tool,
      input: t.input,
      text: t.text,
      isError: t.isError === true,
    })),
    toolResults: (message.toolResults ?? []).map((r) => ({
      tool_use_id: r.tool_use_id,
      text: r.text,
      isError: r.isError,
    })),
  };
}

/**
 * An unchanged message is the engine's own (handle included); a changed one is rebuilt from
 * the original without its handle, keeping only the listed tool blocks with the given texts.
 */
function rebuild(input: readonly SessionMessage[], kept: KeptMessage): SessionMessage {
  const original = input[kept.from];
  if (!original) throw new Error(`answer names message ${kept.from} of ${input.length}`);
  if (!kept.toolUses && !kept.toolResults) return original;
  const uses = new Map(original.toolUses.map((t) => [t.tool_use_id, t]));
  const results = new Map((original.toolResults ?? []).map((r) => [r.tool_use_id, r]));
  const message: SessionMessage = {
    role: original.role,
    text: original.text,
    toolUses: (kept.toolUses ?? []).map(({ tool_use_id, text }) => {
      const use = uses.get(tool_use_id);
      if (!use) throw new Error(`unknown tool_use ${tool_use_id}`);
      return text === undefined || text === use.text ? use : { ...use, text, result: undefined };
    }),
  };
  const toolResults = (kept.toolResults ?? []).map(({ tool_use_id, text }) => {
    const result = results.get(tool_use_id);
    if (!result) throw new Error(`unknown tool_result ${tool_use_id}`);
    return text === result.text ? result : { ...result, text, result: undefined };
  });
  if (toolResults.length > 0) message.toolResults = toolResults;
  return message;
}

// ---------------------------------------------------------------- jev-router

let routerOptions: PluginOptions = {};
let escalateAfter = DEFAULT_ESCALATE_AFTER;
let initModel = DEFAULT_INIT_MODEL;
let record: SessionRecord = { sessionId: '', mode: 'off' };
let section = '';
let rules: Record<string, Permission> = {};
let tiers: string[] = ['haiku', 'sonnet', 'opus'];
let sessionAlias: string | null = null;
let offline = false;
let turn = newTurn();
// Per routed subagent: the model it runs on and the files its prompt named.
const agentModels = new Map<string, string>();
const agentFiles = new Map<string, string[]>();
// Session-wide: how many levels up the next subagent touching a file starts, after errors there.
const escalated = new Map<string, number>();

const isActive = () => record.mode === 'on';
const aliasOf = (model: string | undefined | null) =>
  model ? tiers.find((t) => model.toLowerCase().includes(t)) : undefined;
const bump = (alias: string) => tiers[Math.min(tiers.length - 1, tiers.indexOf(alias) + 1)] ?? alias;

// Set by register from the jev_compacter_mode option; shown on the status line with the router.
let compacterOn = true;

function idleStatus(): string {
  const router = !isActive()
    ? 'router off'
    : offline
      ? `router offline → ${sessionAlias ?? 'session model'}`
      : 'routing subagents';
  return `◆ jev · compact ${compacterOn ? 'on' : 'off'} · ${router} · ${skillsStatus()}`;
}

async function routerFields($: Engine) {
  return {
    session_id: await $.session.id(),
    project_dir: await $.session.root(),
    session_model: await $.session.model(),
    options: toolOptions(routerOptions),
  };
}

async function saveRecord($: Engine) {
  await $.store.set(STORE_KEY, record);
}

async function refresh($: Engine) {
  try {
    const answer = await runTool<RenderAnswer>($, routerOptions, ROUTER_MODULE, 'render', await routerFields($));
    section = answer.section;
    rules = answer.rules;
    tiers = answer.tiers.length > 0 ? answer.tiers : tiers;
    sessionAlias = answer.current;
  } catch (error) {
    section = '';
    $.ui.log(`jev-router: could not render its prompt section (${errorText(error)})`);
  }
  $.ui.status(idleStatus());
}

async function setMode($: Engine, mode: Mode) {
  record = { ...record, mode };
  await saveRecord($);
  await refresh($);
}

async function routerSessionStart($: Engine) {
  await $.command.register({
    name: ROUTER_COMMAND,
    description: 'Jev model router: on or off; init, why, stats',
    argumentHint: '[on|off|init|why|stats]',
  });
  const sessionId = await $.session.id();
  const stored = (await $.store.get(STORE_KEY)) as Partial<SessionRecord> | undefined;
  if (stored && stored.sessionId === sessionId) {
    record = { sessionId, mode: oneOf(MODES, stored.mode, record.mode) };
  } else {
    record = { ...record, sessionId };
    await saveRecord($);
  }
  escalated.clear();
  await refresh($);
}

async function runCommand($: Engine, e: CommandRunInput): Promise<CommandRunResult> {
  const [verb = '', ...rest] = e.args.trim().split(/\s+/).filter(Boolean);
  const arg = rest.join(' ');
  try {
    if (verb === '') return { text: `jev-router: ${record.mode}\n\n${USAGE}` };
    if ((MODES as readonly string[]).includes(verb)) {
      await setMode($, verb as Mode);
      return {
        text:
          verb === 'on'
            ? 'jev-router: on for this session. File changes go through subagents; Jev picks each one\'s model.'
            : 'jev-router: off for this session.',
      };
    }
    if (verb === 'why' || verb === 'stats') {
      const { text } = await runTool<{ text: string }>($, routerOptions, ROUTER_MODULE, verb, await routerFields($));
      return { text };
    }
    if (verb === 'init') return await runInit($, arg);
    return { text: USAGE };
  } catch (error) {
    $.ui.status(idleStatus());
    return { text: `jev-router: ${errorText(error)}` };
  }
}

/** A one-token call: the full id if it answers, the alias alone (id learned later), or unavailable. */
async function checkModel(
  $: Engine,
  alias: string,
  id: string,
  sessionModel: string,
): Promise<{ id: string; available: boolean }> {
  if (aliasOf(sessionModel) === alias) return { id: sessionModel, available: true };
  for (const model of id ? [id, alias] : [alias]) {
    try {
      const r = await $.model.complete({ model, prompt: 'Reply OK.', maxTokens: 1, timeoutMs: 30_000 });
      if (r.isAnswered || r.reason !== 'api-error' || !MODEL_GONE.has(r.error)) {
        return { id: model === alias ? '' : model, available: true };
      }
    } catch {
      // the engine refused to send it: a blocked or unknown model
    }
  }
  return { id: '', available: false };
}

async function runInit($: Engine, arg: string): Promise<CommandRunResult> {
  const depthMatch = /--depth[ =](\d+)/.exec(arg);
  const depth = depthMatch ? Number(depthMatch[1]) : undefined;
  const directive = arg.replace(/--depth[ =]\d+/, '').trim().replace(/^["']|["']$/g, '');
  $.ui.status('◆ jev · scanning…');
  const base = await routerFields($);
  const scan = await runTool<{ system: string; prompt: string; paths: number; models: { alias: string; id: string }[] }>(
    $,
    routerOptions,
    ROUTER_MODULE,
    'scan',
    { ...base, directive, depth },
  );
  $.ui.status('◆ jev · checking model access…');
  const checks = Object.fromEntries(
    await Promise.all(scan.models.map(async (m) => [m.alias, await checkModel($, m.alias, m.id, base.session_model)] as const)),
  );
  $.ui.status(`◆ jev · writing rules for ${scan.paths} paths…`);
  const reply = await $.model.complete({
    model: initModel,
    system: scan.system,
    prompt: scan.prompt,
    maxTokens: 8_000,
    timeoutMs: 180_000,
  });
  if (reply.usage) recordUsage('init', reply.usage, { model: initModel });
  if (!reply.isAnswered) {
    $.ui.status(idleStatus());
    return { text: `jev-router: the rules writer (${initModel}) gave no answer (${reply.reason})` };
  }
  const saved = await runTool<{ text: string; count: number }>($, routerOptions, ROUTER_MODULE, 'init_save', {
    ...base,
    directive,
    depth,
    reply: reply.text,
    checks,
  });
  const turnedOn = !isActive();
  if (turnedOn) await setMode($, 'on');
  else await refresh($);
  return { text: saved.text + (turnedOn ? '\n\nRouting is now on for this session.' : '') };
}

function composeSections(sections: readonly PromptComposeSection[]): readonly PromptComposeSection[] {
  if (!isActive() || !section) return sections;
  return [...sections.filter((s) => s.id !== SECTION_ID), { id: SECTION_ID, text: section, scope: 'session' }];
}

/** The main loop may not change files; a routed subagent only those its model is allowed. */
async function guardWrite(
  $: Engine,
  e: Record<string, unknown> & { agentId?: string },
): Promise<{ deny?: string; watched: boolean }> {
  if (!isActive()) return { watched: false };
  const { paths, kind } = writeTargets(e);
  if (paths.length === 0) return { watched: false };
  if (e.agentId === undefined) {
    turn.deniedCount += 1;
    return {
      watched: false,
      deny:
        'jev-router: you cannot change files yourself while routing is on. Spawn a subagent with the Agent ' +
        'tool: the goal, the exact file paths, and what done looks like. Jev picks its model.',
    };
  }
  const running = agentModels.get(e.agentId);
  if (!running) return { watched: false };
  const root = await $.session.root();
  for (const target of paths) {
    const rel = relPath(target, root);
    const permission = lookup(rules, rel, tiers);
    const allowed = kind === 'write' ? permission.write : permission.delete;
    if (allowed.includes(running)) continue;
    turn.deniedCount += 1;
    const why =
      allowed.length === 0
        ? `no model may ${kind} ${rel}`
        : `${running} may not ${kind} ${rel}; it needs ${allowed.join(' or ')}`;
    notify($, `🔒 jev: ${why}`, 8_000);
    return {
      watched: false,
      deny: `jev-router: ${why} (.optim-jev/jev_router/rules.json). Leave it and say so in your final report.`,
    };
  }
  return { watched: true };
}

function countWriteResult($: Engine, agentId: string | undefined, isError: boolean) {
  if (!isError || agentId === undefined) return;
  const errors = (turn.errors.get(agentId) ?? 0) + 1;
  turn.errors.set(agentId, errors);
  if (errors !== escalateAfter) return;
  const from = agentModels.get(agentId);
  const files = agentFiles.get(agentId) ?? [];
  if (!from || files.length === 0 || bump(from) === from) return;
  for (const f of files) escalated.set(f, (escalated.get(f) ?? 0) + 1);
  turn.escalations.push({ from, to: bump(from), files });
  notify($, `⬆ jev: ${from} hit ${escalateAfter} errors; the next subagent for ${files.join(', ')} starts on ${bump(from)}`, 8_000);
}

async function routeSpawn($: Engine, e: AgentSpawnInput): Promise<{ model?: string; prompt?: string; files: string[] }> {
  if (!isActive() || e.fork || e.isTeammate) return { files: [] };
  $.ui.status('◆ jev · routing subagent…');
  try {
    const answer = await runTool<SpawnAnswer>($, routerOptions, ROUTER_MODULE, 'spawn', {
      ...(await routerFields($)),
      description: e.description,
      prompt: e.prompt,
      escalated: Object.fromEntries(escalated),
    });
    offline = answer.jev_failed !== null;
    turn.spawned += 1;
    notify($, answer.toast, 6_000);
    $.ui.status(idleStatus());
    return { model: answer.model, prompt: answer.appendix ? e.prompt + answer.appendix : undefined, files: answer.files };
  } catch (error) {
    offline = true;
    $.ui.log(`jev-router: subagent not routed (${errorText(error)})`, { to: 'debug' });
    $.ui.status(idleStatus());
    return { files: [] };
  }
}

async function routerTurnComplete($: Engine, e: TurnCompleteInput) {
  if (e.agentId !== undefined) return;
  if (isActive() && (turn.spawned > 0 || turn.escalations.length > 0 || turn.deniedCount > 0)) {
    try {
      await runTool($, routerOptions, ROUTER_MODULE, 'outcome', {
        ...(await routerFields($)),
        record: {
          turn_id: e.turnId,
          reason: e.reason,
          spawned: turn.spawned,
          errors: [...turn.errors.values()].reduce((a, b) => a + b, 0),
          escalations: turn.escalations,
          denials: turn.deniedCount,
        },
      });
    } catch (error) {
      $.ui.log(`jev-router: outcome not logged (${errorText(error)})`, { to: 'debug' });
    }
  }
  $.ui.status(idleStatus());
}

/**
 * The router's own hooks. `session.start` and `turn.complete` are shared with the compacter, whose
 * hooks call routerSessionStart and routerTurnComplete (one unmatched hook per event per plugin).
 */
function registerRouter(on: On, pluginOptions: PluginOptions): void {
  routerOptions = pluginOptions;
  escalateAfter = numberOption(routerOptions, 'jev_router_escalate_after', DEFAULT_ESCALATE_AFTER);
  initModel =
    typeof routerOptions['jev_router_init_model'] === 'string' && routerOptions['jev_router_init_model']
      ? routerOptions['jev_router_init_model']
      : DEFAULT_INIT_MODEL;
  record = { sessionId: '', mode: oneOf(MODES, routerOptions['jev_router_mode'], 'off') };

  on('command.run', { command: 'jev-route' }, async ($, e) => runCommand($, e));

  on('prompt.compose', async ($, e, next) => {
    const result = await next(e);
    return { sections: composeSections(result.sections) };
  });

  on('turn.start', async ($, e, next) => {
    turn = newTurn();
    return next(e);
  });

  on('tool.call', { tool: ['Edit', 'Write', 'NotebookEdit', 'Bash', 'PowerShell'] }, async ($, e, next) => {
    const verdict = await guardWrite($, e as unknown as Record<string, unknown> & { agentId?: string });
    if (verdict.deny !== undefined) return { deny: verdict.deny };
    const result = await next(e);
    if (verdict.watched) countWriteResult($, e.agentId, result.isError === true);
    return result;
  });

  on('agent.spawn', async ($, e, next) => {
    const routed = await routeSpawn($, e);
    const result = await next({
      ...e,
      ...(routed.model ? { model: routed.model } : {}),
      ...(routed.prompt ? { prompt: routed.prompt } : {}),
    });
    if (routed.model && result.agentId) {
      agentModels.set(result.agentId, aliasOf(result.model) ?? routed.model);
      agentFiles.set(result.agentId, routed.files);
      // Ties this agent's `turn` records to the router's spawn record.
      usageBuffer.push({
        ts: Math.round(Date.now() / 1000),
        kind: 'spawned',
        agent_id: result.agentId,
        description: e.description,
        routed_model: routed.model,
        model: result.model,
        files: routed.files,
      });
    }
    return result;
  });
}

// ---------------------------------------------------------------- jev-skills

const SKILLS_MODULE = 'optim_jev.tools.jev_skills.tool';
const SKILLS_COMMAND = 'jev-skills';
const SKILLS_STORE_KEY = 'jev_skills_session';
const SKILLS_MODES = ['off', 'on'] as const;
const SKILLS_SCOPES = ['project', 'global'] as const;
const SKILLS_TIMEOUT_MS = 30_000;
const SKILLS_USAGE = [
  'Usage: /jev-skills [on | off]',
  '       /jev-skills scope project|global',
  '       /jev-skills why | stats | reindex',
].join('\n');
const FOLLOW_UP =
  /^(y(es)?|no?|ok(ay)?|sure|continue|go( ahead)?|do it|proceed|thanks?|thank you|lgtm|looks good|next|done)[.! ]*$/i;
type SkillsRecord = { sessionId: string; mode: (typeof SKILLS_MODES)[number]; scope: (typeof SKILLS_SCOPES)[number] };

let skillsOptions: PluginOptions = {};
let skills: SkillsRecord = { sessionId: '', mode: 'off', scope: 'project' };
// Folders outside the project holding skills in scope: Claude may read them without asking.
let skillDirs: string[] = [];
let skillCount = 0;
let lastPicks: string[] = [];
let listingNote = '';

const skillsOn = () => skills.mode === 'on';
const normPath = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();

function skillsStatus(): string {
  return skillsOn() ? `skills ${skills.scope} (${skillCount})` : 'skills off';
}

async function skillsFields($: Engine) {
  return {
    session_id: await $.session.id(),
    project_dir: await $.session.root(),
    scope: skills.scope,
    options: toolOptions(skillsOptions),
  };
}

async function reindex($: Engine) {
  if (!skillsOn()) {
    skillDirs = [];
    return;
  }
  try {
    const answer = await runTool<{ count: number; dirs: string[] }>($, skillsOptions, SKILLS_MODULE, 'index', await skillsFields($));
    skillCount = answer.count;
    skillDirs = answer.dirs.map(normPath);
  } catch (error) {
    $.ui.log(`jev-skills: could not index skills (${errorText(error)})`);
  }
}

async function skillsSessionStart($: Engine) {
  await $.command.register({
    name: SKILLS_COMMAND,
    description: 'Jev skill picker: on or off, project or global scope; why, stats',
    argumentHint: '[on|off|scope project|global|why|stats|reindex]',
  });
  const sessionId = await $.session.id();
  const stored = (await $.store.get(SKILLS_STORE_KEY)) as Partial<SkillsRecord> | undefined;
  skills =
    stored && stored.sessionId === sessionId
      ? { sessionId, mode: oneOf(SKILLS_MODES, stored.mode, skills.mode), scope: oneOf(SKILLS_SCOPES, stored.scope, skills.scope) }
      : { ...skills, sessionId };
  await $.store.set(SKILLS_STORE_KEY, skills);
  const hasListSkills = (await $.tool.list()).some((t) => t.name === 'ListSkills');
  listingNote =
    'Skills are not listed here: optim-jev\'s skill picker shortlists the relevant ones with each request. ' +
    (hasListSkills
      ? 'If you need a skill that was not shortlisted, search with the ListSkills tool.'
      : 'The person can also run any skill with /<name>.');
  await reindex($);
}

async function runSkillsCommand($: Engine, e: CommandRunInput): Promise<CommandRunResult> {
  const [verb = '', arg = ''] = e.args.trim().split(/\s+/).filter(Boolean);
  try {
    if (verb === '') return { text: `jev-skills: ${skillsStatus()}\n\n${SKILLS_USAGE}` };
    if ((SKILLS_MODES as readonly string[]).includes(verb) || verb === 'scope' || verb === 'reindex') {
      if (verb === 'scope') {
        if (!(SKILLS_SCOPES as readonly string[]).includes(arg)) return { text: SKILLS_USAGE };
        skills = { ...skills, scope: arg as SkillsRecord['scope'] };
      } else if (verb !== 'reindex') {
        skills = { ...skills, mode: verb as SkillsRecord['mode'] };
      }
      await $.store.set(SKILLS_STORE_KEY, skills);
      await reindex($);
      $.ui.status(idleStatus());
      const extra =
        skillsOn() && skills.scope === 'global'
          ? `\nClaude may read files in ${skillDirs.length} skill folder(s) outside the project without asking.`
          : '';
      return { text: `jev-skills: ${skillsStatus()}${extra}` };
    }
    if (verb === 'why' || verb === 'stats') {
      const { text } = await runTool<{ text: string }>($, skillsOptions, SKILLS_MODULE, verb, await skillsFields($));
      return { text };
    }
    return { text: SKILLS_USAGE };
  } catch (error) {
    return { text: `jev-skills: ${errorText(error)}` };
  }
}

async function previousAnswer($: Engine): Promise<string> {
  try {
    const messages = await $.session.messages();
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m && m.role === 'assistant' && m.text.trim()) return m.text;
    }
  } catch {
    // no transcript yet
  }
  return '';
}

/** The shortlist for one prompt, as context beside it; nothing for slash commands and short follow-ups. */
async function shortlistFor($: Engine, e: PromptSubmitInput): Promise<string | undefined> {
  const text = e.text.trim();
  const kind = e.origin.kind;
  if (!skillsOn() || skillCount === 0 || (kind !== 'composer' && kind !== 'bridge')) return undefined;
  if (text.startsWith('/') || text.length < 12 || FOLLOW_UP.test(text)) return undefined;
  $.ui.status(`◆ jev · picking skills (${skillCount})…`);
  try {
    const answer = await runTool<{ picks: string[]; context: string; failed: string | null }>(
      $,
      skillsOptions,
      SKILLS_MODULE,
      'shortlist',
      { ...(await skillsFields($)), prompt: e.text, previous: await previousAnswer($) },
      SKILLS_TIMEOUT_MS,
    );
    lastPicks = answer.picks;
    if (answer.picks.length > 0) notify($, `jev skills · ${answer.picks.join(', ')}`, 6_000);
    return answer.context || undefined;
  } catch (error) {
    $.ui.log(`jev-skills: no shortlist (${errorText(error)})`, { to: 'debug' });
    return undefined;
  } finally {
    $.ui.status(idleStatus());
  }
}

function isSkillPath(input: unknown): boolean {
  if (!input || typeof input !== 'object') return false;
  const record = input as Record<string, unknown>;
  const raw = record['file_path'] ?? record['path'];
  if (typeof raw !== 'string' || !raw) return false;
  const path = normPath(raw);
  return skillDirs.some((dir) => path === dir || path.startsWith(dir + '/'));
}

function registerSkills(on: On, pluginOptions: PluginOptions): void {
  skillsOptions = pluginOptions;
  skills = {
    sessionId: '',
    mode: oneOf(SKILLS_MODES, pluginOptions['jev_skills_mode'], 'off'),
    scope: oneOf(SKILLS_SCOPES, pluginOptions['jev_skills_scope'], 'project'),
  };

  on('command.run', { command: SKILLS_COMMAND }, async ($, e) => runSkillsCommand($, e));

  // The built-in listing of every skill goes; a fixed note takes its place so the cache keeps it.
  on('prompt.attachment', async ($, e, next) => {
    if (!skillsOn() || e.type !== 'skill_listing') return next(e);
    return { text: listingNote };
  });

  on('prompt.submit', async ($, e, next) => {
    const context = await shortlistFor($, e);
    return next(context ? { ...e, context: [...(e.context ?? []), context] } : e);
  });

  // Global scope: reading a shortlisted skill's own files outside the project needs no prompt.
  on('tool.check', { tool: ['Read', 'Glob', 'Grep'] }, async ($, e, next) => {
    const verdict = await next(e);
    if (verdict.decision !== 'ask' || !skillsOn() || skills.scope !== 'global' || !isSkillPath(e.input)) return verdict;
    return { decision: 'allow', reason: 'optim-jev: a skill folder in the skill picker\'s global scope' };
  });

  on('skill.prompt', async ($, e, next) => {
    const result = await next(e);
    if (skillsOn()) {
      try {
        await runTool($, skillsOptions, SKILLS_MODULE, 'loaded', {
          ...(await skillsFields($)),
          skill: e.skill,
          shortlisted: lastPicks.includes(e.skill),
        });
      } catch (error) {
        $.ui.log(`jev-skills: load not logged (${errorText(error)})`, { to: 'debug' });
      }
    }
    return result;
  });
}

// ------------------------------------------------------------- jev-compacter

// The level a compaction this plugin starts runs at, read by its session.compact.
let pendingLevel: Level | null = null;
let checking = false;

/** Claude Code's own summary: its real token counts are the baseline jev-compacter is measured against. */
async function recordSummary(
  $: Engine,
  e: SessionCompactInput,
  result: SessionCompactResult,
  level: Level | null,
): Promise<void> {
  if (!result.messages || !result.usage) return;
  recordUsage('summary', result.usage, {
    trigger: e.trigger,
    level,
    agent_id: e.agentId ?? null,
    model: await $.session.model(),
    tokens_before: result.tokensBefore ?? null,
    tokens_after: result.tokensAfter ?? null,
  });
}

async function autoCompact($: Engine, options: PluginOptions): Promise<void> {
  checking = true;
  try {
    const fields = await sessionFields($, options);
    const soft = options['jev_compacter_soft_percent'];
    if (fields.percent >= (typeof soft === 'number' ? soft : DEFAULT_SOFT_PERCENT)) {
      const { percent: _percent, ...request } = fields;
      const { level } = await runTool<CheckAnswer>($, options, TOOL_MODULE, 'check', request);
      if (level) {
        pendingLevel = level;
        await $.session.compact();
      }
    }
  } catch (error) {
    $.ui.log(`jev-compacter: auto-compaction check skipped (${errorText(error)})`);
  } finally {
    pendingLevel = null;
    checking = false;
  }
}

export const register: Register = (on: On, options: PluginOptions) => {
  compacterOn = options['jev_compacter_mode'] !== 'off';
  registerRouter(on, options);
  registerSkills(on, options);

  let lastMessage = '';

  on('command.run', { command: 'jev-compact' }, async ($, e) => {
    if (e.args.trim() !== 'stats') return { text: 'Usage: /jev-compact stats' };
    try {
      const { percent: _percent, ...fields } = await sessionFields($, options);
      const { text } = await runTool<{ text: string }>($, options, TOOL_MODULE, 'stats', fields);
      return { text };
    } catch (error) {
      return { text: `jev-compacter: ${errorText(error)}` };
    }
  });

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'jev-compact',
      description: "Jev compacter: this session's compactions and what they cost",
      argumentHint: 'stats',
    });
    await routerSessionStart($);
    await skillsSessionStart($);
    $.ui.status(idleStatus());
    return next(e);
  });

  on('session.compact', async ($, e, next) => {
    if (!compacterOn || e.agentId !== undefined || e.trigger === 'precompute') {
      const result = await next(e);
      await recordSummary($, e, result, null);
      return result;
    }
    const level: Level =
      e.trigger === 'manual' ? 'manual' : e.trigger === 'auto' ? 'hard' : (pendingLevel ?? 'soft');
    pendingLevel = null;
    const mustShrink = level === 'manual' || level === 'hard';
    try {
      const { percent: _percent, ...fields } = await sessionFields($, options);
      const answer = await runTool<CompactAnswer>($, options, TOOL_MODULE, 'compact', {
        ...fields,
        level,
        messages: e.messages.map(wire),
      });
      for (const line of answer.log) $.ui.log(line, { to: 'debug' });
      if (answer.message) notify($, (lastMessage = answer.message));
      if (answer.action === 'apply' && answer.messages) {
        return {
          messages: answer.messages.map((kept) => rebuild(e.messages, kept)),
          tokensBefore: fields.usage.used_tokens,
          tokensAfter: answer.tokensAfter,
        };
      }
      if (answer.action !== 'summarize') return { skip: answer.message || 'jev-compacter: nothing to compact' };
    } catch (error) {
      if (!mustShrink) {
        notify($, (lastMessage = `jev-compacter: ${errorText(error)}; compaction skipped`));
        return { skip: `jev-compacter: ${errorText(error)}` };
      }
      notify($, (lastMessage = `jev-compacter: ${errorText(error)}; falling back to built-in summary`));
    }
    // Jev's prune wasn't applied and the context must shrink: Claude Code's built-in summary.
    const result = await next(e);
    await recordSummary($, e, result, level);
    return result;
  });

  on('turn.complete', async ($, e, next) => {
    if (e.usage) {
      recordUsage('turn', e.usage, {
        agent_id: e.agentId ?? null,
        turn_id: e.turnId,
        reason: e.reason,
        duration_ms: e.durationMs,
        model: e.usage.model,
      });
    }
    await routerTurnComplete($, e);
    if (e.agentId === undefined) {
      if (compacterOn && !checking) await autoCompact($, options);
      // After autoCompact, so a compaction this turn started lands in the same flush.
      await flushUsage($, options);
    }
    return next(e);
  });
};
