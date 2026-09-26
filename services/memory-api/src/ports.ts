// Boundaries of the service. The ingestion and search logic only depend on
// these interfaces; Ollama and Qdrant adapters implement them, and tests use
// in-memory fakes.
import type { ChunkPoint, IndexedNote, SearchHit, SearchOptions } from './domain.js';

export interface Embedder {
  readonly model: string;
  /** Embeds note chunks (document side of the retrieval task). */
  embedDocuments(texts: string[]): Promise<number[][]>;
  /** Embeds a user question (query side of the retrieval task). */
  embedQuery(text: string): Promise<number[]>;
  /** Resolves when the embedding service is reachable. */
  health(): Promise<void>;
}

export interface VectorStore {
  /** Creates the collection and payload indexes if missing; fails on a dimension mismatch. */
  ensureCollection(dimensions: number): Promise<void>;
  listIndexedNotes(): Promise<IndexedNote[]>;
  upsertChunks(points: ChunkPoint[]): Promise<void>;
  /** Deletes the chunks of a note whose index is >= fromChunkIndex (all chunks by default). */
  deleteNote(path: string, fromChunkIndex?: number): Promise<void>;
  search(vector: number[], options: SearchOptions): Promise<SearchHit[]>;
  /** Resolves when the store is reachable and accepts the credentials. */
  health(): Promise<void>;
}

export interface Logger {
  info(obj: object, msg?: string): void;
  warn(obj: object, msg?: string): void;
  error(obj: object, msg?: string): void;
}

/** Error raised when Ollama or Qdrant fails or is unreachable. */
export class UpstreamError extends Error {
  constructor(
    readonly service: 'ollama' | 'qdrant',
    message: string,
    readonly status?: number,
  ) {
    super(`${service}: ${message}`);
    this.name = 'UpstreamError';
  }
}
