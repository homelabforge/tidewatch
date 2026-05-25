/**
 * Minimal ANSI SGR parser for container log display.
 *
 * Handles the subset of escape sequences emitted by Python's `colorlog`,
 * `rich`, and most stdlib `logging` formatters: foreground colors (30–37,
 * 90–97), bright/bold (1), and dim (2). Background colors, 256-color, and
 * truecolor sequences are recognised and skipped silently. All other CSI
 * sequences (cursor movement, erase, etc.) are stripped.
 */

export interface AnsiSegment {
  text: string;
  className: string;
}

// eslint-disable-next-line no-control-regex -- ANSI escape sequences begin with \x1b
const ANSI_REGEX = /\x1b\[([0-9;]*)m|\x1b\[[\d;?]*[a-ln-zA-Z]/g;

const FG_COLORS: Record<number, string> = {
  30: 'text-gray-500',
  31: 'text-red-400',
  32: 'text-green-400',
  33: 'text-yellow-400',
  34: 'text-blue-400',
  35: 'text-fuchsia-400',
  36: 'text-cyan-400',
  37: 'text-gray-200',
  90: 'text-gray-500',
  91: 'text-red-300',
  92: 'text-green-300',
  93: 'text-yellow-300',
  94: 'text-blue-300',
  95: 'text-fuchsia-300',
  96: 'text-cyan-300',
  97: 'text-white',
};

interface SgrState {
  fg: string | null;
  bold: boolean;
  dim: boolean;
}

const EMPTY_STATE: SgrState = { fg: null, bold: false, dim: false };

function applyCodes(state: SgrState, codes: number[]): SgrState {
  let next = { ...state };
  let i = 0;
  while (i < codes.length) {
    const code = codes[i];
    if (code === 0) {
      next = { ...EMPTY_STATE };
    } else if (code === 1) {
      next.bold = true;
    } else if (code === 2) {
      next.dim = true;
    } else if (code === 22) {
      next.bold = false;
      next.dim = false;
    } else if (code === 39) {
      next.fg = null;
    } else if (FG_COLORS[code]) {
      next.fg = FG_COLORS[code];
    } else if (code === 38 && codes[i + 1] === 5) {
      // 256-color: \x1b[38;5;Nm — skip the N
      i += 2;
    } else if (code === 38 && codes[i + 1] === 2) {
      // truecolor: \x1b[38;2;R;G;Bm — skip R,G,B
      i += 4;
    }
    // 40–47, 100–107 (bg), other codes — ignored
    i += 1;
  }
  return next;
}

function stateToClass(state: SgrState): string {
  const parts: string[] = [];
  if (state.fg) parts.push(state.fg);
  if (state.bold) parts.push('font-bold');
  if (state.dim) parts.push('opacity-70');
  return parts.join(' ');
}

export function parseAnsi(input: string): AnsiSegment[] {
  const segments: AnsiSegment[] = [];
  let state: SgrState = { ...EMPTY_STATE };
  let cursor = 0;

  ANSI_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = ANSI_REGEX.exec(input)) !== null) {
    if (match.index > cursor) {
      segments.push({
        text: input.slice(cursor, match.index),
        className: stateToClass(state),
      });
    }
    // match[1] is captured only for SGR (`m`); other CSI sequences have no group
    if (match[1] !== undefined) {
      const codes = match[1] === '' ? [0] : match[1].split(';').map((s) => Number(s) || 0);
      state = applyCodes(state, codes);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < input.length) {
    segments.push({ text: input.slice(cursor), className: stateToClass(state) });
  }
  return segments;
}

export function stripAnsi(input: string): string {
  return input.replace(ANSI_REGEX, '');
}
