import { posix } from 'node:path';

import type { ParsedNote, WikiLink } from '../domain.js';
import { splitFrontmatter } from './frontmatter.js';
import { maskInlineCode, parseHeading, scanLines } from './lines.js';

// `#tag`, `#nested/tag`, `#tag-with_dash`, preceded by start or whitespace.
// Obsidian requires at least one non-digit character.
const INLINE_TAG = /(?:^|[\s(])#([\p{L}\p{N}_/-]+)/gu;
const WIKILINK = /(!?)\[\[([^[\]\n]+?)\]\]/g;

/** Parses an Obsidian note: frontmatter, title, tags and wikilinks. */
export function parseNote(path: string, content: string): ParsedNote {
  const { data, body, error } = splitFrontmatter(content.replace(/\r\n?/g, '\n'));

  // Text outside code, used for tags and links.
  const prose: string[] = [];
  let firstH1: string | undefined;
  for (const line of scanLines(body)) {
    if (line.inCode) {
      continue;
    }
    const heading = parseHeading(line.text);
    if (heading?.level === 1 && firstH1 === undefined) {
      firstH1 = heading.text;
    }
    // A heading line is not a tag: `# Title` has a space after `#`.
    prose.push(maskInlineCode(line.text));
  }
  const text = prose.join('\n');

  const note: ParsedNote = {
    path,
    title: resolveTitle(path, data, firstH1),
    frontmatter: data,
    tags: collectTags(data, text),
    links: collectLinks(text),
    body,
  };
  if (error !== undefined) {
    note.frontmatterError = error;
  }
  return note;
}

function resolveTitle(path: string, data: Record<string, unknown>, firstH1: string | undefined): string {
  const fromFrontmatter = data['title'];
  if (typeof fromFrontmatter === 'string' && fromFrontmatter.trim() !== '') {
    return fromFrontmatter.trim();
  }
  return firstH1 ?? posix.basename(path, posix.extname(path));
}

function collectTags(data: Record<string, unknown>, text: string): string[] {
  const tags = new Set<string>();
  const add = (raw: string): void => {
    const tag = raw.trim().replace(/^#/, '').toLowerCase();
    if (tag !== '' && !/^[\d/]+$/.test(tag)) {
      tags.add(tag);
    }
  };

  for (const key of ['tags', 'tag']) {
    const value = data[key];
    if (Array.isArray(value)) {
      value.filter((v): v is string | number => typeof v === 'string' || typeof v === 'number').forEach((v) => add(String(v)));
    } else if (typeof value === 'string') {
      value.split(/[,\s]+/).forEach(add);
    }
  }
  for (const match of text.matchAll(INLINE_TAG)) {
    add(match[1] ?? '');
  }
  return [...tags].sort((a, b) => a.localeCompare(b));
}

function collectLinks(text: string): WikiLink[] {
  const links = new Map<string, WikiLink>();
  for (const match of text.matchAll(WIKILINK)) {
    const link = parseWikiLink(match[2] ?? '', match[1] === '!');
    if (link !== undefined) {
      links.set(`${link.embed ? '!' : ''}${link.target}#${link.heading ?? ''}|${link.alias ?? ''}`, link);
    }
  }
  return [...links.values()];
}

/** Parses the inside of `[[...]]`: `target#heading|alias`. */
export function parseWikiLink(inner: string, embed = false): WikiLink | undefined {
  const [destination = '', ...aliasParts] = inner.split('|');
  const alias = aliasParts.join('|').trim();
  const hashIndex = destination.indexOf('#');
  const rawTarget = hashIndex === -1 ? destination : destination.slice(0, hashIndex);
  const heading = hashIndex === -1 ? '' : destination.slice(hashIndex + 1).trim();
  const target = rawTarget.trim().replace(/\.md$/i, '');

  // `[[#Heading]]` points inside the current note: no target note.
  if (target === '') {
    return undefined;
  }
  const link: WikiLink = { target, embed };
  if (heading !== '') {
    link.heading = heading;
  }
  if (alias !== '') {
    link.alias = alias;
  }
  return link;
}
