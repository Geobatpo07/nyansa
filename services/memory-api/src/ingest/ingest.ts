import type { ChunkPoint, ParsedNote } from '../domain.js';
import { chunkNote, type ChunkOptions } from '../markdown/chunk.js';
import { parseNote } from '../markdown/parse.js';
import type { Embedder, Logger, VectorStore } from '../ports.js';
import { listNotes, readNote, sha256, type VaultFile } from '../vault/vault.js';
import { planIngest, type IngestMode } from './plan.js';

// Bump when the chunking or payload format changes: every note is then
// reindexed by the next incremental run.
const CHUNKER_VERSION = 'chunker-v1';

export interface IngestReport {
  mode: IngestMode;
  startedAt: string;
  durationMs: number;
  notes: {
    scanned: number;
    indexed: number;
    unchanged: number;
    deleted: number;
    failed: number;
  };
  chunks: { upserted: number };
  errors: { path: string; message: string }[];
}

export class IngestInProgressError extends Error {
  constructor() {
    super('an ingestion is already running');
    this.name = 'IngestInProgressError';
  }
}

export interface IngestorDeps {
  vaultPath: string;
  embedder: Embedder;
  store: VectorStore;
  chunking: ChunkOptions;
  logger: Logger;
  now?: () => Date;
}

export class Ingestor {
  readonly indexVersion: string;
  private running = false;
  private collectionReady = false;
  private readonly now: () => Date;

  constructor(private readonly deps: IngestorDeps) {
    this.now = deps.now ?? (() => new Date());
    this.indexVersion = sha256(`${CHUNKER_VERSION}|${deps.embedder.model}|${deps.chunking.maxChars}`).slice(0, 12);
  }

  get isRunning(): boolean {
    return this.running;
  }

  /** Runs one ingestion. Only one run at a time; a concurrent call fails fast. */
  async run(mode: IngestMode): Promise<IngestReport> {
    if (this.running) {
      throw new IngestInProgressError();
    }
    this.running = true;
    try {
      return await this.execute(mode);
    } finally {
      this.running = false;
    }
  }

  private async execute(mode: IngestMode): Promise<IngestReport> {
    const started = this.now();
    const { store, logger } = this.deps;
    await this.ensureCollection();

    const files = await listNotes(this.deps.vaultPath);
    const contents = new Map<string, { file: VaultFile; content: string; hash: string }>();
    for (const file of files) {
      const { content, hash } = await readNote(file);
      contents.set(file.path, { file, content, hash });
    }

    const plan = planIngest(
      [...contents.values()].map(({ file, hash }) => ({ path: file.path, hash })),
      await store.listIndexedNotes(),
      mode,
      this.indexVersion,
    );

    const report: IngestReport = {
      mode,
      startedAt: started.toISOString(),
      durationMs: 0,
      notes: { scanned: files.length, indexed: 0, unchanged: plan.unchanged.length, deleted: 0, failed: 0 },
      chunks: { upserted: 0 },
      errors: [],
    };

    for (const path of plan.toIndex) {
      const note = contents.get(path);
      if (note === undefined) {
        continue;
      }
      try {
        report.chunks.upserted += await this.indexNote(path, note.content, note.hash);
        report.notes.indexed += 1;
      } catch (err) {
        report.notes.failed += 1;
        report.errors.push({ path, message: err instanceof Error ? err.message : String(err) });
        logger.warn({ path, err }, 'note indexing failed');
      }
    }

    for (const path of plan.toDelete) {
      try {
        await store.deleteNote(path);
        report.notes.deleted += 1;
      } catch (err) {
        report.errors.push({ path, message: err instanceof Error ? err.message : String(err) });
      }
    }

    report.durationMs = this.now().getTime() - started.getTime();
    logger.info({ ...report.notes, chunks: report.chunks.upserted, mode }, 'ingestion finished');
    return report;
  }

  /** Indexes one note and returns the number of chunks written. */
  private async indexNote(path: string, content: string, hash: string): Promise<number> {
    const note = parseNote(path, content);
    if (note.frontmatterError !== undefined) {
      this.deps.logger.warn({ path, error: note.frontmatterError }, 'invalid frontmatter ignored');
    }
    const chunks = chunkNote(note.body, note.title, this.deps.chunking);
    const vectors = await this.deps.embedder.embedDocuments(chunks.map((chunk) => embeddingText(note, chunk.section, chunk.text)));
    if (vectors.length !== chunks.length) {
      throw new Error(`expected ${chunks.length} embeddings, received ${vectors.length}`);
    }

    const indexedAt = this.now().toISOString();
    const links = [...new Set(note.links.map((link) => link.target))].sort((a, b) => a.localeCompare(b));
    const points: ChunkPoint[] = chunks.map((chunk, i) => ({
      id: pointId(path, chunk.index),
      vector: vectors[i] as number[],
      payload: {
        path,
        title: note.title,
        tags: note.tags,
        links,
        section: chunk.section,
        chunk_index: chunk.index,
        chunk_count: chunks.length,
        text: chunk.text,
        note_hash: hash,
        index_version: this.indexVersion,
        indexed_at: indexedAt,
      },
    }));

    // Upsert first (same ids overwrite the previous version), then drop the
    // chunks the note no longer has. The note is never absent from the index.
    await this.deps.store.upsertChunks(points);
    await this.deps.store.deleteNote(path, chunks.length);
    return points.length;
  }

  private async ensureCollection(): Promise<void> {
    if (this.collectionReady) {
      return;
    }
    const [probe] = await this.deps.embedder.embedDocuments(['dimension probe']);
    if (probe === undefined || probe.length === 0) {
      throw new Error('the embedding model returned an empty vector');
    }
    await this.deps.store.ensureCollection(probe.length);
    this.collectionReady = true;
  }
}

/** Text sent to the embedding model: the note title and section give each chunk its context. */
export function embeddingText(note: Pick<ParsedNote, 'title'>, section: string, text: string): string {
  const header = section === '' ? note.title : `${note.title} > ${section}`;
  return `${header}\n\n${text}`;
}

/** Deterministic UUID for a chunk, so reindexing a note overwrites its points. */
export function pointId(path: string, chunkIndex: number): string {
  const hex = sha256(`${path}\u0000${chunkIndex}`).slice(0, 32).split('');
  hex[12] = '5'; // version nibble
  hex[16] = ((Number.parseInt(hex[16] ?? '0', 16) & 0x3) | 0x8).toString(16); // RFC 4122 variant
  const h = hex.join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}
