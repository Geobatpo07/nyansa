// In-memory stand-ins for Ollama and Qdrant. They implement the same ports
// as the real adapters, so the ingestion and search logic run unchanged.
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';

import type { ChunkPoint, IndexedNote, SearchHit, SearchOptions } from '../src/domain.js';
import type { Embedder, Logger, VectorStore } from '../src/ports.js';

const DIMENSIONS = 64;

/**
 * Bag-of-words embedding: each word lands in one of 64 buckets. Texts that
 * share words get similar vectors, which is enough to test ranking.
 */
export class FakeEmbedder implements Embedder {
  readonly model = 'fake-embed';
  documentCalls = 0;
  documentsEmbedded = 0;
  failOn?: ((text: string) => boolean) | undefined;

  embedDocuments(texts: string[]): Promise<number[][]> {
    this.documentCalls += 1;
    this.documentsEmbedded += texts.length;
    const failing = texts.find((text) => this.failOn?.(text) === true);
    if (failing !== undefined) {
      return Promise.reject(new Error('embedding failed'));
    }
    return Promise.resolve(texts.map(embed));
  }

  embedQuery(text: string): Promise<number[]> {
    return Promise.resolve(embed(text));
  }

  health(): Promise<void> {
    return Promise.resolve();
  }
}

function embed(text: string): number[] {
  const vector = new Array<number>(DIMENSIONS).fill(0);
  for (const word of text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []) {
    let hash = 0;
    for (const char of word) {
      hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    }
    vector[hash % DIMENSIONS] = (vector[hash % DIMENSIONS] ?? 0) + 1;
  }
  return vector;
}

export class InMemoryStore implements VectorStore {
  readonly points = new Map<string, ChunkPoint>();
  dimensions?: number;

  ensureCollection(dimensions: number): Promise<void> {
    if (this.dimensions !== undefined && this.dimensions !== dimensions) {
      return Promise.reject(new Error('dimension mismatch'));
    }
    this.dimensions = dimensions;
    return Promise.resolve();
  }

  listIndexedNotes(): Promise<IndexedNote[]> {
    return Promise.resolve(
      [...this.points.values()]
        .filter((point) => point.payload.chunk_index === 0)
        .map(({ payload }) => ({ path: payload.path, hash: payload.note_hash, version: payload.index_version })),
    );
  }

  upsertChunks(points: ChunkPoint[]): Promise<void> {
    for (const point of points) {
      this.points.set(point.id, point);
    }
    return Promise.resolve();
  }

  deleteNote(path: string, fromChunkIndex = 0): Promise<void> {
    for (const [id, point] of this.points) {
      if (point.payload.path === path && point.payload.chunk_index >= fromChunkIndex) {
        this.points.delete(id);
      }
    }
    return Promise.resolve();
  }

  search(vector: number[], options: SearchOptions): Promise<SearchHit[]> {
    const hits = [...this.points.values()]
      .filter((point) => options.tags === undefined || options.tags.some((tag) => point.payload.tags.includes(tag)))
      .map((point) => ({ score: cosine(vector, point.vector), payload: point.payload }))
      .filter((hit) => options.minScore === undefined || hit.score >= options.minScore)
      .sort((a, b) => b.score - a.score)
      .slice(0, options.limit);
    return Promise.resolve(hits);
  }

  health(): Promise<void> {
    return Promise.resolve();
  }

  /** Paths currently indexed, with their chunk count. */
  notes(): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const { payload } of this.points.values()) {
      counts[payload.path] = (counts[payload.path] ?? 0) + 1;
    }
    return counts;
  }
}

function cosine(a: number[], b: number[]): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  a.forEach((value, i) => {
    const other = b[i] ?? 0;
    dot += value * other;
    normA += value * value;
    normB += other * other;
  });
  return normA === 0 || normB === 0 ? 0 : dot / Math.sqrt(normA * normB);
}

export const silentLogger: Logger = { info: () => undefined, warn: () => undefined, error: () => undefined };

/** Temporary vault on disk. */
export class TempVault {
  private constructor(readonly root: string) {}

  static async create(): Promise<TempVault> {
    return new TempVault(await mkdtemp(join(tmpdir(), 'nyansa-vault-')));
  }

  async write(path: string, content: string): Promise<void> {
    const absolute = join(this.root, path);
    await mkdir(dirname(absolute), { recursive: true });
    await writeFile(absolute, content, 'utf8');
  }

  async remove(path: string): Promise<void> {
    await rm(join(this.root, path));
  }

  async dispose(): Promise<void> {
    await rm(this.root, { recursive: true, force: true });
  }
}
