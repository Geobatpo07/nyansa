"""Obsidian Markdown: frontmatter, title, tags, wikilinks and chunking."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from .domain import Chunk, ParsedNote, WikiLink

_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*")
# A YAML block on the very first line, closed by `---` or `...`.
_FRONTMATTER = re.compile(r"---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
# `#tag`, `#nested/tag`, `#tag-with_dash`, preceded by start or whitespace.
_INLINE_TAG = re.compile(r"(?:\A|[\s(])#([\w/-]+)")
_WIKILINK = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
# `[text](target)` or `[text](<target with spaces> "title")`.
_MARKDOWN_LINK = re.compile(r"\[[^\[\]\n]*\]\(\s*(<[^<>\n]+>|[^\s()]+)(?:\s+\"[^\"\n]*\")?\s*\)")
_INLINE_CODE = re.compile(r"(`+)[^`]*?\1")
_NEWLINES = re.compile(r"\r\n?")


@dataclass(frozen=True)
class _Line:
    text: str
    # True for fence delimiters and every line between them.
    in_code: bool


def _scan_lines(markdown: str) -> list[_Line]:
    """Normalizes line endings and marks the lines that belong to fenced code blocks."""
    scanned: list[_Line] = []
    fence: str | None = None
    for text in _NEWLINES.sub("\n", markdown).split("\n"):
        match = _FENCE.match(text)
        if fence is None:
            if match:
                fence = match[1]
            scanned.append(_Line(text, match is not None))
            continue
        scanned.append(_Line(text, True))
        # A closing fence uses the same character, is at least as long, and has no info string.
        if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and text.strip() == match[1]:
            fence = None
    return scanned


def _parse_heading(line: str) -> tuple[int, str] | None:
    """Parses an ATX heading (`## Title`) into (level, text)."""
    match = _HEADING.fullmatch(line)
    if not match or not match[2].strip():
        return None
    return len(match[1]), match[2].strip()


def _mask_inline_code(line: str) -> str:
    """Replaces inline code spans with spaces so their content is not read as tags or links."""
    return _INLINE_CODE.sub(lambda span: " " * len(span[0]), line)


def split_frontmatter(content: str) -> tuple[dict[object, object], str, str | None]:
    """Splits the YAML frontmatter from a note into (data, body, error).

    Invalid YAML does not fail the note: the block is dropped from the body
    and the error is reported.
    """
    match = _FRONTMATTER.match(content)
    if not match:
        return {}, content, None
    body = content[match.end() :]
    try:
        data = yaml.safe_load(match[1])
    except yaml.YAMLError as err:
        return {}, body, str(err)
    if data is None:
        return {}, body, None
    if not isinstance(data, dict):
        return {}, body, "frontmatter is not a mapping"
    return data, body, None


def parse_note(path: str, content: str) -> ParsedNote:
    """Parses an Obsidian note: frontmatter, title, tags and wikilinks."""
    data, body, error = split_frontmatter(_NEWLINES.sub("\n", content))

    # Text outside code, used for tags and links.
    prose: list[str] = []
    first_h1: str | None = None
    for line in _scan_lines(body):
        if line.in_code:
            continue
        heading = _parse_heading(line.text)
        if heading and heading[0] == 1 and first_h1 is None:
            first_h1 = heading[1]
        # A heading line is not a tag: `# Title` has a space after `#`.
        prose.append(_mask_inline_code(line.text))
    text = "\n".join(prose)

    return ParsedNote(
        path=path,
        title=_resolve_title(path, data, first_h1),
        frontmatter=data,
        tags=_collect_tags(data, text),
        links=_collect_links(text),
        body=body,
        frontmatter_error=error,
        markdown_links=list(
            dict.fromkeys(m[1].removeprefix("<").removesuffix(">") for m in _MARKDOWN_LINK.finditer(text))
        ),
    )


def _resolve_title(path: str, data: dict[object, object], first_h1: str | None) -> str:
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return first_h1 if first_h1 is not None else PurePosixPath(path).stem


def _collect_tags(data: dict[object, object], text: str) -> list[str]:
    tags: set[str] = set()

    def add(raw: str) -> None:
        tag = raw.strip().removeprefix("#").lower()
        # Obsidian requires at least one non-digit character.
        if tag and not re.fullmatch(r"[0-9/]+", tag):
            tags.add(tag)

    for key in ("tags", "tag"):
        value = data.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str | int | float) and not isinstance(item, bool):
                    add(str(item))
        elif isinstance(value, str):
            for item in re.split(r"[,\s]+", value):
                add(item)
    for match in _INLINE_TAG.finditer(text):
        add(match[1])
    return sorted(tags)


def _collect_links(text: str) -> list[WikiLink]:
    links: dict[WikiLink, None] = {}
    for match in _WIKILINK.finditer(text):
        link = parse_wikilink(match[2], embed=match[1] == "!")
        if link is not None:
            links[link] = None
    return list(links)


def parse_wikilink(inner: str, embed: bool = False) -> WikiLink | None:
    """Parses the inside of `[[...]]`: `target#heading|alias`."""
    destination, _, alias = inner.partition("|")
    raw_target, _, heading = destination.partition("#")
    target = re.sub(r"\.md\Z", "", raw_target.strip(), flags=re.IGNORECASE)
    # `[[#Heading]]` points inside the current note: no target note.
    if not target:
        return None
    return WikiLink(target, embed, heading.strip() or None, alias.strip() or None)


def chunk_note(body: str, title: str, max_chars: int) -> list[Chunk]:
    """Splits a note body into chunks that follow its heading structure.

    1. The body is cut into sections at each ATX heading (outside code blocks).
       Each section remembers its heading path, e.g. ["Setup", "Docker"].
    2. A section is cut into blocks: paragraphs separated by blank lines, with
       each fenced code block kept whole.
    3. Blocks are packed into chunks of at most `max_chars`. A block longer
       than that is split by lines (code), then sentences, then characters.

    Chunks never span two sections. Each note yields at least one chunk: a
    note with no text is represented by its title so it stays searchable.
    """
    if max_chars < 50:
        raise ValueError("max_chars must be at least 50")
    chunks: list[Chunk] = []
    for headings, blocks in _split_sections(body):
        for text in _pack(_split_blocks(blocks, max_chars), "\n\n", max_chars):
            chunks.append(Chunk(len(chunks), " > ".join(headings), headings, text))
    return chunks or [Chunk(0, "", [], title)]


def _split_sections(body: str) -> list[tuple[list[str], list[str]]]:
    """Returns the (heading path, blocks) of every section that has content."""
    sections: list[tuple[list[str], list[str]]] = []
    stack: list[tuple[int, str]] = []
    headings: list[str] = []
    blocks: list[str] = []
    paragraph: list[str] = []
    code: list[str] | None = None

    def flush_paragraph() -> None:
        text = "\n".join(paragraph).strip()
        if text:
            blocks.append(text)
        paragraph.clear()

    for line in _scan_lines(body):
        if line.in_code:
            if code is None:
                flush_paragraph()
                code = []
            code.append(line.text)
            continue
        if code is not None:
            blocks.append("\n".join(code))
            code = None

        heading = _parse_heading(line.text)
        if heading:
            flush_paragraph()
            sections.append((headings, blocks))
            while stack and stack[-1][0] >= heading[0]:
                stack.pop()
            stack.append(heading)
            headings, blocks = [text for _, text in stack], []
            continue

        if line.text.strip():
            paragraph.append(line.text)
        else:
            flush_paragraph()
    if code is not None:
        # Unclosed fence: keep what was read.
        blocks.append("\n".join(code))
    flush_paragraph()
    sections.append((headings, blocks))
    return [section for section in sections if section[1]]


def _split_blocks(blocks: list[str], max_chars: int) -> list[str]:
    return [piece for block in blocks for piece in _split_oversized(block, max_chars)]


def _split_oversized(block: str, max_chars: int) -> list[str]:
    """Splits a block longer than max_chars: by lines, then sentences, then characters."""
    if len(block) <= max_chars:
        return [block]
    for pattern, joiner in ((r"\n", "\n"), (r"(?<=[.!?…])\s+", " ")):
        parts = [part for part in re.split(pattern, block) if part.strip()]
        if len(parts) > 1:
            return _split_blocks(_pack(parts, joiner, max_chars, allow_oversized=True), max_chars)
    return [block[start : start + max_chars] for start in range(0, len(block), max_chars)]


def _pack(parts: list[str], joiner: str, max_chars: int, allow_oversized: bool = False) -> list[str]:
    """Joins consecutive parts while the result fits in max_chars.

    With allow_oversized, a part longer than max_chars still starts its own
    group (it is split later); otherwise every part already fits.
    """
    packed: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}{joiner}{part}" if current else part
        if len(candidate) <= max_chars or (allow_oversized and not current):
            current = candidate
        else:
            packed.append(current)
            current = part
    if current or allow_oversized:
        packed.append(current)
    return packed
