/* Hallmark · component: terminal dashboard · genre: modern-minimal · theme: warm orange
 * pre-emit critique: P5 H5 E5 S5 R5 V4 · states and focus: Claude Code Button
 */
export type CompactionOutcome =
  | { kind: 'not_run' }
  | { kind: 'applied'; freedTokensEst: number }
  | { kind: 'deferred'; freedTokensEst: number }
  | { kind: 'builtin' }
  | { kind: 'nothing' }
  | { kind: 'skipped' };

export type RouterDecision = {
  task: string;
  model: string;
  effort?: string | null;
  source: 'jev' | 'rules' | 'escalation' | 'claude' | 'fallback' | 'session';
  escalated: number;
};

export type SkillsOutcome =
  | { kind: 'not_run'; picks: string[] }
  | { kind: 'picked'; picks: string[] }
  | { kind: 'none'; picks: string[] }
  | { kind: 'jev_offline'; picks: string[] }
  | { kind: 'unavailable'; picks: string[] };

export type DashboardView = {
  contextPercent: number | null;
  activity: string | null;
  compacter: {
    enabled: boolean;
    softPercent: number;
    hardPercent: number;
    outcome: CompactionOutcome;
    degraded: boolean;
  };
  router: {
    mode: 'on' | 'off';
    routing: boolean;
    offline: boolean;
    hasRules: boolean;
    decision: RouterDecision | null;
  };
  skills: {
    mode: 'on' | 'off';
    scope: 'project' | 'global';
    count: number;
    indexing: boolean;
    picking: boolean;
    outcome: SkillsOutcome;
  };
};

export type DashboardActions = {
  compact: () => unknown;
  toggleRouter: () => unknown;
  toggleSkills: () => unknown;
};

const ACCENT = '#d97757';
const WARNING = '#f0b35f';
const BACKGROUND = '#191411';
export const DASHBOARD_STAR_COLUMNS = 40;
export const DASHBOARD_STAR_ROWS = 3;
export const DASHBOARD_STAR_FRAME_MS = 220;
export const DASHBOARD_STAR_SPACING = 11;

const particleNoise = (seed: number) => {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return value - Math.floor(value);
};

const smoothstep = (value: number) => value * value * (3 - 2 * value);

/** One independently timed particle per horizontal zone; each respawn gets a fresh position. */
export function dashboardStarPoints(columns: number, rows: number, frame: number) {
  const count = Math.ceil(columns / DASHBOARD_STAR_SPACING);
  return Array.from({ length: count }, (_, slot) => {
    const start = slot * DASHBOARD_STAR_SPACING;
    const width = Math.min(DASHBOARD_STAR_SPACING, columns - start);
    const seed = slot * 47 + 11;
    const lifetime = 18 + Math.floor(particleNoise(seed + 5) * 22);
    const shifted = frame + Math.floor(particleNoise(seed + 17) * lifetime);
    const run = Math.floor(shifted / lifetime);
    const age = (shifted % lifetime) / lifetime;
    const cycleSeed = seed + run * 197;
    const glow =
      age < 0.2
        ? smoothstep(age / 0.2)
        : age < 0.58
          ? 1
          : age < 0.82
            ? smoothstep((0.82 - age) / 0.24)
            : 0;
    return {
      x: start + Math.floor(particleNoise(cycleSeed) * Math.max(1, width)),
      y: (slot + run + Math.floor(particleNoise(cycleSeed + 29) * rows)) % rows,
      glow: glow * (0.45 + particleNoise(cycleSeed + 73) * 0.55),
    };
  });
}

/** A sparse terminal-native field whose independent particles fade, rest, and respawn. */
export function dashboardStarFrame(
  frame: number,
  columns = DASHBOARD_STAR_COLUMNS,
  rows = DASHBOARD_STAR_ROWS,
): string {
  const words = new Uint32Array(columns * rows * 3);
  const particles = new Map(
    dashboardStarPoints(columns, rows, frame).map((particle) => [particle.y * columns + particle.x, particle]),
  );
  for (let row = 0; row < rows; row++)
    for (let x = 0; x < columns; x++) {
      const i = (row * columns + x) * 3;
      const particle = particles.get(row * columns + x);
      const glow = particle?.glow ?? 0;
      words[i] = glow > 0.16 ? 0x00b7 : 0x20;
      words[i + 1] = glow > 0.68 ? 0xd97757 : 0x513327;
      words[i + 2] = 0x191411;
    }
  return new Uint8Array(words.buffer).toBase64();
}

const DASHBOARD_STARS_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="60" viewBox="0 0 1600 60" preserveAspectRatio="none"><style>.s{fill:${ACCENT};opacity:0;animation:tw 7s ease-in-out infinite}@keyframes tw{0%,100%{opacity:0}18%{opacity:.42}58%{opacity:.18}78%{opacity:0}}@media(prefers-reduced-motion:reduce){.s{animation:none;opacity:.14}}</style><circle class="s" cx="34" cy="12" r=".8" style="animation-duration:5.4s;animation-delay:-1.1s"/><circle class="s" cx="146" cy="43" r=".8" style="animation-duration:8.1s;animation-delay:-5.3s"/><circle class="s" cx="278" cy="20" r=".8" style="animation-duration:6.7s;animation-delay:-2.7s"/><circle class="s" cx="404" cy="49" r=".8" style="animation-duration:9.3s;animation-delay:-7.4s"/><circle class="s" cx="538" cy="9" r=".8" style="animation-duration:7.6s;animation-delay:-3.1s"/><circle class="s" cx="674" cy="35" r=".8" style="animation-duration:5.9s;animation-delay:-4.8s"/><circle class="s" cx="818" cy="16" r=".8" style="animation-duration:10.2s;animation-delay:-2.2s"/><circle class="s" cx="956" cy="47" r=".8" style="animation-duration:6.3s;animation-delay:-.9s"/><circle class="s" cx="1094" cy="25" r=".8" style="animation-duration:8.8s;animation-delay:-6.5s"/><circle class="s" cx="1232" cy="8" r=".8" style="animation-duration:7.1s;animation-delay:-1.5s"/><circle class="s" cx="1374" cy="41" r=".8" style="animation-duration:9.7s;animation-delay:-8.9s"/><circle class="s" cx="1542" cy="18" r=".8" style="animation-duration:5.7s;animation-delay:-.3s"/></svg>`;

function title(value: string): string {
  return value ? value[0]!.toUpperCase() + value.slice(1) : value;
}

function short(value: string, limit: number): string {
  const one = value.replace(/\s+/g, ' ').trim();
  return one.length <= limit ? one : `${one.slice(0, limit - 1)}…`;
}

function tokens(value: number): string {
  return value >= 1000 ? `~${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k` : `~${value}`;
}

export function compacterText(view: DashboardView, _narrow = false): string {
  const c = view.compacter;
  if (!c.enabled) return 'Compacter off';
  const percent = view.contextPercent === null ? '—' : `${Math.round(view.contextPercent)}%`;
  const threshold = `soft ${c.softPercent}% · hard ${c.hardPercent}%`;
  const outcome =
    c.outcome.kind === 'applied'
      ? `freed ${tokens(c.outcome.freedTokensEst)}`
      : c.outcome.kind === 'deferred'
        ? `deferred ${tokens(c.outcome.freedTokensEst)}`
        : c.outcome.kind === 'builtin'
          ? 'built-in summary'
          : c.outcome.kind === 'nothing'
            ? 'nothing to prune'
            : c.outcome.kind === 'skipped'
              ? 'skipped'
              : '';
  return [`Context ${percent}`, threshold, outcome].filter(Boolean).join(' · ');
}

export function routerText(view: DashboardView, narrow = false): string {
  const r = view.router;
  if (r.mode === 'off') return 'Router off';
  if (r.routing) return 'Router routing…';
  if (r.offline && !r.decision) return 'Router offline · session model';
  if (!r.decision) {
    if (!r.hasRules) return 'Router on · no rules · run /jev-route init';
    return 'Router on';
  }
  const up = r.decision.escalated ? ` ↑${r.decision.escalated}` : '';
  const effort = r.decision.effort ? ` · ${r.decision.effort}` : '';
  if (narrow) return `Router on → ${title(r.decision.model)}${effort}${up}`;
  if (r.decision.source === 'fallback' || r.decision.source === 'session') {
    return `Router on · ${short(r.decision.task, 22)} → ${title(r.decision.model)}${effort} · session model · Jev offline${up}`;
  }
  const source = r.decision.source === 'jev' ? 'Jev' : r.decision.source === 'claude' ? 'Claude' : r.decision.source;
  return `Router on · ${short(r.decision.task, 22)} → ${title(r.decision.model)}${effort} via ${source}${up}`;
}

export function skillsText(view: DashboardView, narrow = false): string {
  const s = view.skills;
  if (s.mode === 'off') return 'Skills off';
  if (s.indexing) return 'Skills indexing…';
  if (s.picking) return narrow ? 'Skills picking…' : `Skills picking from ${s.count}…`;
  const base = `Skills ${title(s.scope)} ${s.count}`;
  if (s.outcome.kind === 'unavailable') return `${base} · picker unavailable`;
  if (s.outcome.kind === 'jev_offline') return `${base} · Jev offline · skill names attached`;
  if (s.outcome.kind === 'none') return `${base} · none matched`;
  if (s.outcome.kind !== 'picked') return base;
  const [first, second] = s.outcome.picks;
  const picked = second ? `${first} +${s.outcome.picks.length - 1}` : first;
  return `${base} · ${short(picked ?? '', narrow ? 16 : 24)}`;
}

type Elements = {
  // Claude Code supplies these components for the surface being rendered.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Box: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Text: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Button: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Raster?: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Svg?: any;
};

/** The host can reduce AbovePrompt's height independently of terminal width. */
export function dashboardLayout(columns: number, maxRows = 5) {
  const width = Number.isFinite(columns) ? Math.max(0, Math.floor(columns)) : 0;
  const rows = Number.isFinite(maxRows) ? Math.max(0, Math.floor(maxRows)) : 0;
  return {
    width,
    rows,
    full: width >= 60 && rows >= 5,
    controls: width >= 50 && rows >= 2,
  };
}

export function dashboardTree(
  elements: Elements,
  view: DashboardView,
  actions: DashboardActions,
  columns: number,
  terminal = false,
  starFrame = 0,
  maxRows = 5,
) {
  const { Box, Text, Button } = elements;
  const layout = dashboardLayout(columns, maxRows);
  // No border or fixed-size decoration when the host cannot fit the five-row card.
  // Commands remain available when there is no room for buttons.
  if (terminal && !layout.full) {
    if (!layout.width || !layout.rows) return null;
    const percent = view.contextPercent === null ? '?' : `${Math.round(view.contextPercent)}%`;
    const compact = view.compacter.enabled ? `Ctx ${percent}` : 'Compact off';
    const router = view.router.mode === 'off'
      ? 'off' : view.router.routing ? 'routing' : view.router.offline ? 'offline' : 'on';
    const skills = view.skills.mode === 'off'
      ? 'off' : view.skills.indexing ? 'indexing' : view.skills.picking ? 'picking' : 'on';
    const status = `${compact} | Router ${router} | Skills ${skills}`;
    return (
      <Box
        key="optim-jev-dashboard"
        flexDirection="column"
        width={layout.width}
        height={layout.controls ? 2 : 1}
        overflow="hidden"
      >
        <Box height={1} minWidth={0} overflow="hidden">
          <Text wrap="truncate">{view.activity ? `${status} | ${view.activity}` : status}</Text>
        </Box>
        {layout.controls ? (
          <Box
            key="dashboard-actions"
            flexDirection="row"
            flexWrap="nowrap"
            gap={1}
            height={1}
            minWidth={0}
            overflow="hidden"
          >
            <Button key="dashboard-compact" plain label="Compact" onPress={actions.compact} />
            <Button
              key="dashboard-router"
              plain
              label={`Router ${view.router.mode}`}
              onPress={actions.toggleRouter}
            />
            <Button
              key="dashboard-skills"
              plain
              label={`Skills ${view.skills.mode}`}
              onPress={actions.toggleSkills}
            />
          </Box>
        ) : null}
      </Box>
    );
  }
  const narrow = columns > 0 && columns < 90;
  const compactWarning = view.compacter.degraded;
  const routerWarning = view.router.mode === 'on' && view.router.offline;
  const skillsWarning = view.skills.outcome.kind === 'jev_offline' || view.skills.outcome.kind === 'unavailable';
  const brand = (
    <Box flexShrink={0}>
      <Text color={ACCENT} bold>
        ✦ optim-jev
      </Text>
    </Box>
  );
  const compactControl = (
    <Button key="dashboard-compact" variant="secondary" label="Compact" onPress={actions.compact} />
  );
  const routerControl = (
    <Button
      key="dashboard-router"
      plain
      dimColor={view.router.mode === 'off'}
      label={`${view.router.mode === 'on' ? 'Disable' : 'Enable'} router`}
      onPress={actions.toggleRouter}
    />
  );
  const skillsControl = (
    <Button
      key="dashboard-skills"
      plain
      dimColor={view.skills.mode === 'off'}
      label={`${view.skills.mode === 'on' ? 'Disable' : 'Enable'} skills`}
      onPress={actions.toggleSkills}
    />
  );
  const controls = (
    <Box key="dashboard-actions" flexShrink={0} flexDirection="row" flexWrap="wrap" gap={1} alignItems="center">
      {compactControl}
      {routerControl}
      {skillsControl}
    </Box>
  );
  const starColumns = Math.max(1, columns - 4);
  const terminalStars =
    terminal && columns >= 60 && elements.Raster ? (
      <Box key="dashboard-star-field" position="absolute" top={0} left={0} right={0} bottom={0} overflow="hidden">
        <elements.Raster
          key="dashboard-stars"
          columns={starColumns}
          rows={DASHBOARD_STAR_ROWS}
          cells={dashboardStarFrame(starFrame, starColumns, DASHBOARD_STAR_ROWS)}
        />
      </Box>
    ) : null;
  const desktopStars =
    !terminal && elements.Svg ? (
      <Box key="dashboard-star-field" position="absolute" top={0} right={0} bottom={0}>
        <elements.Svg source={DASHBOARD_STARS_SVG} alt="" width={420} height={60} />
      </Box>
    ) : null;
  return (
    <Box
      key="optim-jev-dashboard"
      position="relative"
      flexDirection="column"
      paddingX={1}
      overflow="hidden"
      backgroundColor={BACKGROUND}
      borderStyle="round"
    >
      {desktopStars}
      {terminalStars}
      {terminal ? (
        <Box flexDirection="column" overflow="hidden">
          <Box flexDirection="row" gap={1} alignItems="center">
            {brand}
            <Text dimColor>·</Text>
            <Box flexGrow={1} flexShrink={1} minWidth={0} overflow="hidden">
              <Text color={compactWarning ? WARNING : undefined} wrap="truncate">
                {view.activity ?? compacterText(view)}
              </Text>
            </Box>
            {compactControl}
          </Box>
          <Box flexDirection="row" gap={1} alignItems="center">
            <Box flexGrow={1} flexShrink={1} minWidth={0} overflow="hidden">
              <Text color={routerWarning ? WARNING : undefined} wrap="truncate">{routerText(view)}</Text>
            </Box>
            {routerControl}
          </Box>
          <Box flexDirection="row" gap={1} alignItems="center">
            <Box flexGrow={1} flexShrink={1} minWidth={0} overflow="hidden">
              <Text color={skillsWarning ? WARNING : undefined} wrap="truncate">{skillsText(view)}</Text>
            </Box>
            {skillsControl}
          </Box>
        </Box>
      ) : (
        <Box flexDirection="column">
          <Box flexDirection="row" gap={1} alignItems="center">
            {brand}
            <Box flexGrow={1} flexShrink={1} minWidth={0} overflow="hidden">
              {view.activity ? (
                <Text color={ACCENT} wrap="truncate">
                  {view.activity}
                </Text>
              ) : null}
            </Box>
            {controls}
          </Box>
          <Text wrap="truncate">
            <Text color={compactWarning ? WARNING : undefined}>{compacterText(view, narrow)}</Text>
            <Text dimColor>{'  │  '}</Text>
            <Text color={routerWarning ? WARNING : undefined}>{routerText(view, narrow)}</Text>
            <Text dimColor>{'  │  '}</Text>
            <Text color={skillsWarning ? WARNING : undefined}>{skillsText(view, narrow)}</Text>
          </Text>
        </Box>
      )}
    </Box>
  );
}
