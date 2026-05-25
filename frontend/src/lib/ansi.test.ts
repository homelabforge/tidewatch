import { describe, it, expect } from 'vitest';
import { parseAnsi, stripAnsi } from './ansi';

const ESC = '\x1b';

describe('stripAnsi', () => {
  it('removes SGR sequences', () => {
    expect(stripAnsi(`${ESC}[34mINFO${ESC}[0m hello`)).toBe('INFO hello');
  });

  it('removes compound SGR sequences', () => {
    expect(stripAnsi(`${ESC}[2;36m[10:20:00]${ESC}[0m msg`)).toBe('[10:20:00] msg');
  });

  it('removes non-SGR CSI sequences (cursor, erase)', () => {
    expect(stripAnsi(`${ESC}[2Kfoo${ESC}[1;5H`)).toBe('foo');
  });

  it('passes plain text through untouched', () => {
    expect(stripAnsi('plain log line')).toBe('plain log line');
  });
});

describe('parseAnsi', () => {
  it('produces a single empty-class segment for plain text', () => {
    const segs = parseAnsi('hello');
    expect(segs).toEqual([{ text: 'hello', className: '' }]);
  });

  it('maps foreground 34 to blue', () => {
    const segs = parseAnsi(`${ESC}[34mINFO${ESC}[0m rest`);
    expect(segs).toEqual([
      { text: 'INFO', className: 'text-blue-400' },
      { text: ' rest', className: '' },
    ]);
  });

  it('handles compound dim+cyan and resets correctly', () => {
    const segs = parseAnsi(`${ESC}[2;36m[ts]${ESC}[0m body`);
    expect(segs[0]).toEqual({ text: '[ts]', className: 'text-cyan-400 opacity-70' });
    expect(segs[1]).toEqual({ text: ' body', className: '' });
  });

  it('skips 256-color sequences without crashing', () => {
    const segs = parseAnsi(`${ESC}[38;5;202mfoo${ESC}[0m`);
    expect(segs).toEqual([{ text: 'foo', className: '' }]);
  });

  it('treats bare ESC[m as reset', () => {
    const segs = parseAnsi(`${ESC}[31mA${ESC}[mB`);
    expect(segs).toEqual([
      { text: 'A', className: 'text-red-400' },
      { text: 'B', className: '' },
    ]);
  });
});
