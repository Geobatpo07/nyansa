import type { ChunkPayload, ChunkPoint, IndexedNote, SearchHit, SearchOptions } from '../domain.js';
import { UpstreamError, type VectorStore } from '../ports.js';
import { requestJson, type FetchFn } from './http.js';

export interface QdrantStoreOptions {
  baseUrl: string;
  apiKey: string;
  collection: string;
  timeoutMs?: number;
  fetchFn?: FetchFn;
}

interface QdrantResponse<T> {
  result: T;
}

interface ScrollResult {
  points: { payload?: Partial<ChunkPayload> }[];
  next_page_offset?: string | number | null;
}

interface QueryResult {
  points: { score: number; payload?: ChunkPayload }[];
}

type Filter = { must: Record<string, unknown>[] };

const PAYLOAD_INDEXES: { field: string; schema: 'keyword' | 'integer' }[] = [
  { field: 'path', schema: 'keyword' },
  { field: 'tags', schema: 'keyword' },
  { field: 'chunk_index', schema: 'integer' },
];

export class QdrantStore implements VectorStore {
  private readonly baseUrl: string;
  private readonly collectionUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchFn: FetchFn;

  constructor(private readonly options: QdrantStoreOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.collectionUrl = `${this.baseUrl}/collections/${encodeURIComponent(options.collection)}`;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchFn = options.fetchFn ?? fetch;
  }

  async ensureCollection(dimensions: number): Promise<void> {
    const { body } = await this.call<QdrantResponse<{ exists: boolean }>>('GET', `${this.collectionUrl}/exists`);
    if (body.result.exists) {
      const info = await this.call<QdrantResponse<{ config: { params: { vectors: { size?: number } } } }>>('GET', this.collectionUrl);
      const size = info.body.result.config.params.vectors.size;
      if (size !== dimensions) {
        throw new UpstreamError(
          'qdrant',
          `collection ${this.options.collection} has vectors of size ${size}, the embedding model produces ${dimensions}; ` +
            'delete the collection or set another QDRANT_COLLECTION',
        );
      }
      return;
    }

    await this.call('PUT', this.collectionUrl, { vectors: { size: dimensions, distance: 'Cosine' } });
    for (const index of PAYLOAD_INDEXES) {
      await this.call('PUT', `${this.collectionUrl}/index?wait=true`, { field_name: index.field, field_schema: index.schema });
    }
  }

  async listIndexedNotes(): Promise<IndexedNote[]> {
    const notes: IndexedNote[] = [];
    let offset: string | number | null | undefined;
    do {
      const { body } = await this.call<QdrantResponse<ScrollResult>>('POST', `${this.collectionUrl}/points/scroll`, {
        // The first chunk of each note carries what incremental indexing needs.
        filter: { must: [{ key: 'chunk_index', match: { value: 0 } }] },
        with_payload: ['path', 'note_hash', 'index_version'],
        with_vector: false,
        limit: 256,
        ...(offset === undefined || offset === null ? {} : { offset }),
      });
      for (const point of body.result.points) {
        const { path, note_hash: hash, index_version: version } = point.payload ?? {};
        if (path !== undefined && hash !== undefined && version !== undefined) {
          notes.push({ path, hash, version });
        }
      }
      offset = body.result.next_page_offset;
    } while (offset !== undefined && offset !== null);
    return notes;
  }

  async upsertChunks(points: ChunkPoint[]): Promise<void> {
    if (points.length === 0) {
      return;
    }
    await this.call('PUT', `${this.collectionUrl}/points?wait=true`, { points });
  }

  async deleteNote(path: string, fromChunkIndex = 0): Promise<void> {
    const filter: Filter = { must: [{ key: 'path', match: { value: path } }] };
    if (fromChunkIndex > 0) {
      filter.must.push({ key: 'chunk_index', range: { gte: fromChunkIndex } });
    }
    await this.call('POST', `${this.collectionUrl}/points/delete?wait=true`, { filter });
  }

  async search(vector: number[], options: SearchOptions): Promise<SearchHit[]> {
    const body: Record<string, unknown> = { query: vector, limit: options.limit, with_payload: true };
    if (options.minScore !== undefined) {
      body['score_threshold'] = options.minScore;
    }
    if (options.tags !== undefined && options.tags.length > 0) {
      body['filter'] = { must: [{ key: 'tags', match: { any: options.tags } }] };
    }
    try {
      const response = await this.call<QdrantResponse<QueryResult>>('POST', `${this.collectionUrl}/points/query`, body);
      return response.body.result.points
        .filter((point): point is { score: number; payload: ChunkPayload } => point.payload !== undefined)
        .map((point) => ({ score: point.score, payload: point.payload }));
    } catch (err) {
      // Nothing ingested yet: no collection means no result, not an error.
      if (err instanceof UpstreamError && err.status === 404) {
        return [];
      }
      throw err;
    }
  }

  async health(): Promise<void> {
    // /collections needs the API key, so this also checks the credentials.
    await this.call('GET', `${this.baseUrl}/collections`, undefined, 5_000);
  }

  private call<T>(method: string, url: string, body?: unknown, timeoutMs = this.timeoutMs): Promise<{ status: number; body: T }> {
    return requestJson<T>(this.fetchFn, 'qdrant', url, {
      method,
      body,
      headers: { 'api-key': this.options.apiKey },
      timeoutMs,
    });
  }
}
