import { describe, expect, it } from 'vitest';

import { splitFrontmatter } from '../src/markdown/frontmatter.js';
import { parseNote, parseWikiLink } from '../src/markdown/parse.js';

describe('splitFrontmatter', () => {
  it('separates a YAML block from the body', () => {
    const result = splitFrontmatter('---\ntitle: Hello\ntags: [a, b]\n---\n# Body\n');
    expect(result.data).toEqual({ title: 'Hello', tags: ['a', 'b'] });
    expect(result.body).toBe('# Body\n');
    expect(result.error).toBeUndefined();
  });

  it('accepts `...` as closing delimiter', () => {
    expect(splitFrontmatter('---\na: 1\n...\ntext').data).toEqual({ a: 1 });
  });

  it('leaves a note without frontmatter untouched', () => {
    expect(splitFrontmatter('# Title\n---\nnot: yaml')).toEqual({ data: {}, body: '# Title\n---\nnot: yaml' });
  });

  it('reports invalid YAML without failing', () => {
    const result = splitFrontmatter('---\ntitle: [unclosed\n---\nbody');
    expect(result.data).toEqual({});
    expect(result.body).toBe('body');
    expect(result.error).toBeTypeOf('string');
  });

  it('rejects a frontmatter that is not a mapping', () => {
    expect(splitFrontmatter('---\n- a\n- b\n---\nbody').error).toBe('frontmatter is not a mapping');
  });
});

describe('parseWikiLink', () => {
  it.each([
    ['Note', { target: 'Note', embed: false }],
    ['Note|Alias', { target: 'Note', alias: 'Alias', embed: false }],
    ['Note#Heading', { target: 'Note', heading: 'Heading', embed: false }],
    ['folder/Note.md#^block|shown', { target: 'folder/Note', heading: '^block', alias: 'shown', embed: false }],
    ['  Spaced  ', { target: 'Spaced', embed: false }],
  ])('parses [[%s]]', (inner, expected) => {
    expect(parseWikiLink(inner)).toEqual(expected);
  });

  it('ignores links to a heading of the same note', () => {
    expect(parseWikiLink('#Local heading')).toBeUndefined();
  });
});

describe('parseNote', () => {
  it('takes the title from the frontmatter, then the first H1, then the file name', () => {
    expect(parseNote('a.md', '---\ntitle: From YAML\n---\n# From H1').title).toBe('From YAML');
    expect(parseNote('a.md', 'intro\n# From H1\n# Second').title).toBe('From H1');
    expect(parseNote('dir/My note.md', 'no heading').title).toBe('My note');
  });

  it('merges frontmatter and inline tags, normalized and deduplicated', () => {
    const note = parseNote(
      'n.md',
      '---\ntags: [Project, "#AI"]\ntag: solo\n---\nWorking on #project and #ideas/nyansa (see #ai).\n',
    );
    expect(note.tags).toEqual(['ai', 'ideas/nyansa', 'project', 'solo']);
  });

  it('accepts tags written as a comma or space separated string', () => {
    expect(parseNote('n.md', '---\ntags: alpha, beta gamma\n---\n').tags).toEqual(['alpha', 'beta', 'gamma']);
  });

  it('does not read headings, numbers, URLs or code as tags', () => {
    const content = [
      '# Heading',
      '## Sub heading',
      'Issue #42 and https://example.com/page#anchor',
      'Inline `#notatag` code',
      '```',
      '#also-not-a-tag [[NotALink]]',
      '```',
      'Real #tag',
    ].join('\n');
    const note = parseNote('n.md', content);
    expect(note.tags).toEqual(['tag']);
    expect(note.links).toEqual([]);
  });

  it('collects wikilinks and embeds, deduplicated', () => {
    const note = parseNote('n.md', 'See [[Alpha]], [[Beta|the beta]] and [[Alpha]] again.\n![[diagram.png]]\n[[Gamma#Setup]]');
    expect(note.links).toEqual([
      { target: 'Alpha', embed: false },
      { target: 'Beta', alias: 'the beta', embed: false },
      { target: 'diagram.png', embed: true },
      { target: 'Gamma', heading: 'Setup', embed: false },
    ]);
  });

  it('keeps the body without the frontmatter and handles CRLF', () => {
    const note = parseNote('n.md', '---\r\ntitle: T\r\n---\r\nLine one\r\n[[Link]]\r\n');
    expect(note.body).toBe('Line one\n[[Link]]\n');
    expect(note.links).toEqual([{ target: 'Link', embed: false }]);
  });

  it('indexes a note with broken frontmatter and reports the error', () => {
    const note = parseNote('n.md', '---\n: : :\n---\n# Still here #tag');
    expect(note.title).toBe('Still here #tag');
    expect(note.tags).toEqual(['tag']);
    expect(note.frontmatterError).toBeTypeOf('string');
  });
});
