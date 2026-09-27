import { parse as parseYaml } from 'yaml';

export interface FrontmatterResult {
  data: Record<string, unknown>;
  body: string;
  error?: string;
}

// A YAML block on the very first line, closed by `---` or `...`.
const FRONTMATTER = /^---[ \t]*\n([\s\S]*?)\n(?:---|\.\.\.)[ \t]*(?:\n|$)/;

/**
 * Splits the YAML frontmatter from a note. Invalid YAML does not fail the
 * note: the block is dropped from the body and the error is reported.
 */
export function splitFrontmatter(content: string): FrontmatterResult {
  const match = FRONTMATTER.exec(content);
  if (!match) {
    return { data: {}, body: content };
  }

  const body = content.slice(match[0].length);
  try {
    const parsed: unknown = parseYaml(match[1] ?? '');
    if (parsed === null || parsed === undefined) {
      return { data: {}, body };
    }
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { data: {}, body, error: 'frontmatter is not a mapping' };
    }
    return { data: parsed as Record<string, unknown>, body };
  } catch (err) {
    return { data: {}, body, error: err instanceof Error ? err.message : String(err) };
  }
}
