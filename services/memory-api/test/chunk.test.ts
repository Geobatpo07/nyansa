import { describe, expect, it } from 'vitest';

import { chunkNote } from '../src/markdown/chunk.js';

const options = { maxChars: 200 };

describe('chunkNote', () => {
  it('creates one chunk per section with its heading path', () => {
    const body = ['Intro text.', '# Setup', 'Install it.', '## Docker', 'Run compose.', '## Tailscale', 'Join.', '# Usage', 'Ask.'].join('\n');
    const chunks = chunkNote(body, 'Title', options);
    expect(chunks.map((c) => [c.section, c.text])).toEqual([
      ['', 'Intro text.'],
      ['Setup', 'Install it.'],
      ['Setup > Docker', 'Run compose.'],
      ['Setup > Tailscale', 'Join.'],
      ['Usage', 'Ask.'],
    ]);
    expect(chunks.map((c) => c.index)).toEqual([0, 1, 2, 3, 4]);
  });

  it('resets deeper headings when a shallower one starts', () => {
    const body = '# A\n### A3\ntext\n## B2\ntext';
    expect(chunkNote(body, 'T', options).map((c) => c.headings)).toEqual([
      ['A', 'A3'],
      ['A', 'B2'],
    ]);
  });

  it('skips sections without content', () => {
    const chunks = chunkNote('# Empty\n\n## Also empty\n## Filled\ncontent', 'T', options);
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.section).toBe('Empty > Filled');
  });

  it('packs paragraphs up to maxChars and never exceeds it', () => {
    const paragraph = 'word '.repeat(15).trim(); // 74 chars
    const body = Array.from({ length: 6 }, () => paragraph).join('\n\n');
    const chunks = chunkNote(body, 'T', options);
    expect(chunks.length).toBe(3);
    for (const chunk of chunks) {
      expect(chunk.text.length).toBeLessThanOrEqual(options.maxChars);
      expect(chunk.text.split('\n\n')).toHaveLength(2);
    }
  });

  it('splits an oversized paragraph on sentences, then on characters', () => {
    const sentences = Array.from({ length: 10 }, (_, i) => `Sentence number ${i} has some words.`).join(' ');
    const chunks = chunkNote(sentences, 'T', options);
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((c) => c.text.length <= options.maxChars)).toBe(true);
    expect(chunks.every((c) => c.text.endsWith('.'))).toBe(true);

    const noSpaces = 'x'.repeat(450);
    expect(chunkNote(noSpaces, 'T', options).map((c) => c.text.length)).toEqual([200, 200, 50]);
  });

  it('keeps a fenced code block whole and ignores headings inside it', () => {
    const code = ['```bash', '# not a heading', 'echo hi', '', 'echo bye', '```'].join('\n');
    const chunks = chunkNote(`# Real\nBefore.\n\n${code}\n\nAfter.`, 'T', options);
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.section).toBe('Real');
    expect(chunks[0]?.text).toContain(code);
  });

  it('keeps an unclosed code block', () => {
    const chunks = chunkNote('text\n\n```\ncode', 'T', options);
    expect(chunks[0]?.text).toBe('text\n\n```\ncode');
  });

  it('represents an empty note by its title', () => {
    expect(chunkNote('\n\n  \n', 'Lonely note', options)).toEqual([{ index: 0, section: '', headings: [], text: 'Lonely note' }]);
  });

  it('rejects an unusable maxChars', () => {
    expect(() => chunkNote('x', 'T', { maxChars: 10 })).toThrow(RangeError);
  });
});
