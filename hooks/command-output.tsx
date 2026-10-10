/** Styled transcript cards for optim-jev's diagnostic slash commands. */

type Elements = {
  // Claude Code supplies these constructors for the active render surface.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Box: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Text: any;
};

const TITLES: Record<string, Partial<Record<string, string>>> = {
  'jev-route': { stats: 'Router stats', why: 'Why this route' },
  'jev-skills': { stats: 'Skills stats', why: 'Why these skills' },
  'jev-compact': { stats: 'Compacter stats' },
};

const TOKEN = /(saved|applied|shortlist(?:ed)?|measured)/gi;
const GOOD = /^(saved|applied|shortlist(?:ed)?|measured)$/i;

function valueParts(Text: Elements['Text'], line: string) {
  return line.split(TOKEN).filter(Boolean).map((part, index) => {
    return GOOD.test(part) ? <Text key={`part-${index}`} bold>{part}</Text> : part;
  });
}

function outputText(Text: Elements['Text'], line: string, _isErrored: boolean) {
  const note = /^(Estimate prices|Prices |Listing and note sizes|No routed subagent turns)/.test(line);

  return (
    <Text wrap="wrap" dimColor={note}>
      {valueParts(Text, line)}
    </Text>
  );
}

type OutputRow =
  | { kind: 'blank' }
  | { kind: 'heading'; text: string }
  | { kind: 'raw'; text: string }
  | { kind: 'note'; text: string }
  | { kind: 'table'; label: string; value: string }
  | { kind: 'text'; text: string };

function outputRow(line: string): OutputRow {
  if (!line) return { kind: 'blank' };
  // Stats reports (src/optim_jev/core/report.py): titles, box-drawn tables, notes.
  if (line.startsWith('▸ ')) return { kind: 'heading', text: line.slice(2) };
  if (/^[┌│├└]/.test(line)) return { kind: 'raw', text: line };
  if (line.startsWith('- ')) return { kind: 'note', text: line.slice(2) };
  const cost = /^\s{2,}(.+?)\s{2,}(\$[\d,.]+.*)$/.exec(line);
  if (cost) return { kind: 'table', label: cost[1]!.trim(), value: cost[2]!.trim() };
  const colon = line.indexOf(':');
  if (!line.startsWith('-') && colon > 0 && colon < 40 && colon < line.length - 1) {
    return { kind: 'table', label: line.slice(0, colon).trim(), value: line.slice(colon + 1).trim() };
  }
  return { kind: 'text', text: line };
}

export function commandOutputTitle(command: string, args: string): string | null {
  const verb = args.trim().split(/\s+/, 1)[0] ?? '';
  return TITLES[command]?.[verb] ?? null;
}

export function commandOutputTree(
  elements: Elements,
  command: string,
  args: string,
  output: string,
  isErrored = false,
  columns = 100,
) {
  const title = commandOutputTitle(command, args);
  if (!title) return null;
  const { Box, Text } = elements;
  const rows = output.split('\n').map(outputRow);
  const widestLabel = Math.max(0, ...rows.map((row) => row.kind === 'table' ? row.label.length : 0));
  const labelWidth = Math.max(12, Math.min(28, widestLabel + 2, Math.floor(columns * 0.36)));

  return (
    <Box key="optim-jev-command-output" flexDirection="column">
      <Text>
        ╭─ ◆ <Text bold>{title}</Text>
      </Text>
      {rows.map((row, index) => (
        <Box key={`output-${index}`} flexDirection="row">
          <Text>│{row.kind === 'blank' ? '' : ' '}</Text>
          {row.kind === 'table' ? (
            <Box flexDirection="row" flexGrow={1} minWidth={0}>
              <Box width={labelWidth} flexShrink={0}>
                <Text bold>
                  {row.label}
                </Text>
              </Box>
              <Box flexGrow={1} flexShrink={1} minWidth={0}>
                {outputText(Text, row.value, isErrored)}
              </Box>
            </Box>
          ) : row.kind === 'heading' ? (
            <Text bold>{row.text}</Text>
          ) : row.kind === 'raw' ? (
            <Text wrap="truncate-end">{valueParts(Text, row.text)}</Text>
          ) : row.kind === 'note' ? (
            <Text wrap="wrap" dimColor>
              {row.text}
            </Text>
          ) : row.kind === 'text' ? outputText(Text, row.text, isErrored) : null}
        </Box>
      ))}
      <Text>╰─</Text>
    </Box>
  );
}
