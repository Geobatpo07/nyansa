import type { Chunk } from '../domain.js';
import { parseHeading, scanLines } from './lines.js';

export interface ChunkOptions {
  /** Upper bound of a chunk's text length, in characters. */
  maxChars: number;
}

interface Section {
  headings: string[];
  blocks: string[];
}

/**
 * Splits a note body into chunks that follow its heading structure:
 *
 * 1. The body is cut into sections at each ATX heading (outside code blocks).
 *    Each section remembers its heading path, e.g. ["Setup", "Docker"].
 * 2. A section is cut into blocks: paragraphs separated by blank lines, with
 *    each fenced code block kept whole.
 * 3. Blocks are packed into chunks of at most `maxChars`. A block longer than
 *    that is split by lines (code), then sentences, then characters.
 *
 * Chunks never span two sections. Each note yields at least one chunk: a note
 * with no text is represented by its title so it stays searchable.
 */
export function chunkNote(body: string, title: string, options: ChunkOptions): Chunk[] {
  if (options.maxChars < 50) {
    throw new RangeError('maxChars must be at least 50');
  }

  const chunks: Chunk[] = [];
  for (const section of splitSections(body)) {
    for (const text of packBlocks(section.blocks, options.maxChars)) {
      chunks.push({
        index: chunks.length,
        section: section.headings.join(' > '),
        headings: section.headings,
        text,
      });
    }
  }

  if (chunks.length === 0) {
    chunks.push({ index: 0, section: '', headings: [], text: title });
  }
  return chunks;
}

function splitSections(body: string): Section[] {
  const sections: Section[] = [];
  const stack: { level: number; text: string }[] = [];
  let current: Section = { headings: [], blocks: [] };
  let paragraph: string[] = [];
  let code: string[] | undefined;

  const flushParagraph = (): void => {
    const text = paragraph.join('\n').trim();
    if (text !== '') {
      current.blocks.push(text);
    }
    paragraph = [];
  };

  for (const line of scanLines(body)) {
    if (line.inCode) {
      if (code === undefined) {
        flushParagraph();
        code = [];
      }
      code.push(line.text);
      continue;
    }
    if (code !== undefined) {
      current.blocks.push(code.join('\n'));
      code = undefined;
    }

    const heading = parseHeading(line.text);
    if (heading !== undefined) {
      flushParagraph();
      sections.push(current);
      while (stack.length > 0 && (stack.at(-1)?.level ?? 0) >= heading.level) {
        stack.pop();
      }
      stack.push(heading);
      current = { headings: stack.map((h) => h.text), blocks: [] };
      continue;
    }

    if (line.text.trim() === '') {
      flushParagraph();
    } else {
      paragraph.push(line.text);
    }
  }
  if (code !== undefined) {
    // Unclosed fence: keep what was read.
    current.blocks.push(code.join('\n'));
  }
  flushParagraph();
  sections.push(current);

  return sections.filter((s) => s.blocks.length > 0);
}

function packBlocks(blocks: string[], maxChars: number): string[] {
  const chunks: string[] = [];
  let current = '';

  for (const block of blocks.flatMap((b) => splitOversized(b, maxChars))) {
    const candidate = current === '' ? block : `${current}\n\n${block}`;
    if (candidate.length <= maxChars) {
      current = candidate;
    } else {
      chunks.push(current);
      current = block;
    }
  }
  if (current !== '') {
    chunks.push(current);
  }
  return chunks;
}

/** Splits a block longer than maxChars: by lines, then sentences, then characters. */
function splitOversized(block: string, maxChars: number): string[] {
  if (block.length <= maxChars) {
    return [block];
  }
  const separators: [RegExp, string][] = [
    [/\n/, '\n'],
    [/(?<=[.!?…])\s+/, ' '],
  ];
  for (const [pattern, joiner] of separators) {
    const parts = block.split(pattern).filter((p) => p.trim() !== '');
    if (parts.length > 1) {
      return packParts(parts, joiner, maxChars).flatMap((p) => splitOversized(p, maxChars));
    }
  }
  const pieces: string[] = [];
  for (let start = 0; start < block.length; start += maxChars) {
    pieces.push(block.slice(start, start + maxChars));
  }
  return pieces;
}

function packParts(parts: string[], joiner: string, maxChars: number): string[] {
  const packed: string[] = [];
  let current = '';
  for (const part of parts) {
    const candidate = current === '' ? part : `${current}${joiner}${part}`;
    if (candidate.length <= maxChars || current === '') {
      current = candidate;
    } else {
      packed.push(current);
      current = part;
    }
  }
  packed.push(current);
  return packed;
}
