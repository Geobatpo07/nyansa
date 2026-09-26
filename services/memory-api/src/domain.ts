// Domain types shared by the parser, the ingestion pipeline and the adapters.

/** A `[[wikilink]]` or `![[embed]]` found in a note. */
export interface WikiLink {
  /** Linked note, as written, without the `.md` extension. */
  target: string;
  /** Heading or block reference after `#`, if any. */
  heading?: string;
  /** Display text after `|`, if any. */
  alias?: string;
  /** True for `![[...]]` embeds. */
  embed: boolean;
}

export interface ParsedNote {
  /** Vault-relative POSIX path, e.g. `projects/nyansa.md`. */
  path: string;
  title: string;
  frontmatter: Record<string, unknown>;
  /** Lower-cased, without `#`, deduplicated, sorted. */
  tags: string[];
  links: WikiLink[];
  /** Markdown content without the frontmatter block. */
  body: string;
  /** Set when the frontmatter could not be parsed; the note is still indexed. */
  frontmatterError?: string;
}

export interface Chunk {
  /** Position of the chunk in the note, starting at 0. */
  index: number;
  /** Heading path of the section, e.g. `Setup > Docker`; empty before the first heading. */
  section: string;
  headings: string[];
  text: string;
}

/** Payload stored with every vector in Qdrant. */
export interface ChunkPayload {
  path: string;
  title: string;
  tags: string[];
  /** Distinct wikilink targets of the whole note (used by the graph in phase 4). */
  links: string[];
  section: string;
  chunk_index: number;
  chunk_count: number;
  text: string;
  /** SHA-256 of the raw note file; drives incremental indexing. */
  note_hash: string;
  /** Changes when the chunking or the embedding model changes. */
  index_version: string;
  indexed_at: string;
}

export interface ChunkPoint {
  id: string;
  vector: number[];
  payload: ChunkPayload;
}

/** What the index knows about a note (read from its first chunk). */
export interface IndexedNote {
  path: string;
  hash: string;
  version: string;
}

export interface SearchHit {
  score: number;
  payload: ChunkPayload;
}

export interface SearchOptions {
  limit: number;
  tags?: string[];
  minScore?: number;
}
