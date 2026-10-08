import type { PluginOptions } from 'claude-code';

export const ROUTER_MODULE = 'optim_jev.tools.jev_router.tool';
export const ROUTER_COMMAND = 'jev-route';
export const SECTION_ID = 'optim-jev:jev-router';
export const STORE_KEY = 'jev_router_session';
export const MODES = ['off', 'on'] as const;
export const DEFAULT_ESCALATE_AFTER = 3;
export const DEFAULT_INIT_MODEL = 'sonnet';
/** Model call errors that mean the account can't use that model (not a transient failure). */
export const MODEL_GONE = new Set<string>(['model_not_found', 'invalid_request', 'oauth_org_not_allowed']);
export const DELETE_COMMANDS = new Set(['rm', 'rmdir', 'del', 'erase', 'unlink', 'remove-item', 'ri', 'mv', 'move', 'move-item']);

/** The routing files Claude may edit itself while routing is on (project-relative). */
export const RULES_FILES = ['.optim-jev/jev_router/rules.json', '.optim-jev/jev_router/RULES.md'];
export const isRulesFile = (rel: string) => RULES_FILES.some((f) => f.toLowerCase() === rel.toLowerCase());

export type Mode = (typeof MODES)[number];
export type Permission = { write: string[]; delete: string[] };
export type RenderAnswer = {
  section: string;
  rules: Record<string, Permission>;
  tiers: string[];
  current: string | null;
  has_rules: boolean;
};
export type SpawnAnswer = { model: string; files: string[]; appendix: string; toast: string; jev_failed: string | null };
export type SessionRecord = { sessionId: string; mode: Mode };
export type Escalation = { from: string; to: string; files: string[] };
export type TurnState = {
  spawned: number;
  errors: Map<string, number>;
  escalations: Escalation[];
  deniedCount: number;
};

export const USAGE = [
  'Usage: /jev-route [on | off]',
  '       /jev-route init [--depth N] [--force] ["what matters in this project"]',
  '       /jev-route why | stats',
].join('\n');

export function newTurn(): TurnState {
  return { spawned: 0, errors: new Map(), escalations: [], deniedCount: 0 };
}

export function oneOf<T extends string>(values: readonly T[], value: unknown, fallback: T): T {
  return typeof value === 'string' && (values as readonly string[]).includes(value) ? (value as T) : fallback;
}

export function numberOption(options: PluginOptions, key: string, fallback: number): number {
  const raw = options[key];
  const value = typeof raw === 'string' ? Number(raw) : raw;
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

export function relPath(file: string, root: string): string {
  const norm = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '');
  let path = norm(file);
  const base = norm(root);
  if (path.toLowerCase().startsWith(base.toLowerCase() + '/')) path = path.slice(base.length + 1);
  while (path.startsWith('./')) path = path.slice(2);
  return path;
}

export function lookup(rules: Record<string, Permission>, rel: string, tiers: string[]): Permission {
  const index = new Map(Object.entries(rules).map(([k, v]) => [k.toLowerCase(), v]));
  let probe = rel.toLowerCase().replace(/\/+$/, '');
  const exact = index.get(probe);
  if (exact) return exact;
  while (probe) {
    const hit = index.get(probe + '/') ?? index.get(probe);
    if (hit) return hit;
    probe = probe.includes('/') ? probe.slice(0, probe.lastIndexOf('/')) : '';
  }
  return { write: tiers, delete: tiers };
}

export function words(segment: string): string[] {
  return [...segment.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)].map((m) => m[1] ?? m[2] ?? m[3] ?? '');
}

/** Paths a shell command deletes or moves away; best effort, not a security boundary. */
export function deletedPaths(command: string): string[] {
  const paths: string[] = [];
  for (const segment of command.split(/&&|\|\||[;|\n]/)) {
    let argv = words(segment.trim());
    if (argv[0] === 'git' && (argv[1] === 'rm' || argv[1] === 'mv')) argv = argv.slice(1);
    if (argv[0] === 'sudo') argv = argv.slice(1);
    const name = (argv[0] ?? '').toLowerCase();
    if (!DELETE_COMMANDS.has(name)) continue;
    const args = argv.slice(1).filter((a) => !a.startsWith('-') && !(a.startsWith('/') && a.length <= 3));
    const isMove = ['mv', 'move', 'move-item'].includes(name);
    paths.push(...(isMove ? args.slice(0, -1) : args));
  }
  return paths.filter(Boolean);
}

export function writeTargets(e: Record<string, unknown>): { paths: string[]; kind: 'write' | 'delete' } {
  const tool = String(e['tool']);
  if (tool === 'Edit' || tool === 'Write') return { paths: [String(e['file_path'] ?? '')], kind: 'write' };
  if (tool === 'NotebookEdit') return { paths: [String(e['notebook_path'] ?? '')], kind: 'write' };
  if (tool === 'Bash' || tool === 'PowerShell') return { paths: deletedPaths(String(e['command'] ?? '')), kind: 'delete' };
  return { paths: [], kind: 'write' };
}

