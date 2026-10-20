"""Context for a chat answer: the relevant chunks grouped by note, with numbered sources to cite."""

from pydantic import Field

from .domain import SearchHit
from .ingest import CamelModel


class Source(CamelModel):
    # Number the answer cites, as [n].
    n: int
    path: str
    title: str
    # Sections of the note the context quotes, in order of relevance.
    sections: list[str]
    # Best similarity score among the note's chunks.
    score: float


class RelatedNote(CamelModel):
    path: str
    title: str
    # Numbers of the sources this note links to or is linked from.
    linked_to: list[int]


class Context(CamelModel):
    query: str
    # False when no chunk passed the relevance threshold: there is nothing to answer from.
    found: bool
    sources: list[Source]
    # Text given to the model: each note in a <note number="n"> tag with its quoted chunks.
    # Small models follow tags better than headers, and do not copy them into the answer.
    context: str
    # Notes linked to the sources in the graph, to list under the answer. Never
    # given to the model: their effect on answers has not been measured.
    related: list[RelatedNote] = Field(default_factory=list)


def build_context(query: str, hits: list[SearchHit], max_chars: int) -> Context:
    """Groups the hits (best first) by note and numbers the notes in order of their best hit.

    Chunks are added while the context stays under max_chars; the best chunk
    is always kept, so a found context is never empty.
    """
    grouped: dict[str, list[SearchHit]] = {}
    used = 0
    for hit in hits:
        size = len(hit.payload["text"])
        if grouped and used + size > max_chars:
            continue
        grouped.setdefault(hit.payload["path"], []).append(hit)
        used += size

    sources: list[Source] = []
    blocks: list[str] = []
    for n, (path, note_hits) in enumerate(grouped.items(), start=1):
        title = note_hits[0].payload["title"]
        sources.append(
            Source(
                n=n,
                path=path,
                title=title,
                sections=list(dict.fromkeys(hit.payload["section"] for hit in note_hits)),
                score=note_hits[0].score,
            )
        )
        quotes = [
            f"Section: {hit.payload['section']}\n{hit.payload['text']}"
            if hit.payload["section"]
            else hit.payload["text"]
            for hit in sorted(note_hits, key=lambda hit: hit.payload["chunk_index"])
        ]
        blocks.append(f'<note number="{n}">\n' + "\n\n".join(quotes) + "\n</note>")

    return Context(query=query, found=bool(sources), sources=sources, context="\n".join(blocks))
