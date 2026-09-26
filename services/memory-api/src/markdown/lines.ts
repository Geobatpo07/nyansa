export interface ScannedLine {
  text: string;
  /** True for fence delimiters and every line between them. */
  inCode: boolean;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;

/** Normalizes line endings and marks the lines that belong to fenced code blocks. */
export function scanLines(markdown: string): ScannedLine[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const scanned: ScannedLine[] = [];
  let fence: { char: string; length: number } | undefined;

  for (const text of lines) {
    const match = FENCE.exec(text);
    if (fence === undefined) {
      if (match?.[1] !== undefined) {
        fence = { char: match[1].charAt(0), length: match[1].length };
        scanned.push({ text, inCode: true });
        continue;
      }
      scanned.push({ text, inCode: false });
      continue;
    }

    scanned.push({ text, inCode: true });
    const closing = match?.[1];
    if (closing !== undefined && closing.charAt(0) === fence.char && closing.length >= fence.length) {
      // A closing fence carries no info string.
      if (text.trim() === closing) {
        fence = undefined;
      }
    }
  }
  return scanned;
}

/** Parses an ATX heading (`## Title`). Returns undefined for other lines. */
export function parseHeading(line: string): { level: number; text: string } | undefined {
  const match = HEADING.exec(line);
  if (match?.[1] === undefined) {
    return undefined;
  }
  const text = (match[2] ?? '').trim();
  return text === '' ? undefined : { level: match[1].length, text };
}

/** Replaces inline code spans with spaces so their content is not read as tags or links. */
export function maskInlineCode(line: string): string {
  return line.replace(/(`+)[^`]*?\1/g, (span) => ' '.repeat(span.length));
}
