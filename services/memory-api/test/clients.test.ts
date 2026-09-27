// The adapters are tested against a stubbed fetch: no Ollama or Qdrant runs.
import { describe, expect, it } from 'vitest';

import type { FetchFn } from '../src/clients/http.js';
import { OllamaEmbedder } from '../src/clients/ollama.js';
import { QdrantStore } from '../src/clients/qdrant.js';
import { UpstreamError } from '../src/ports.js';

interface Call {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

/** Records every request and answers with the responses given in order. */
function stubFetch(...responses: { status?: number; body: unknown }[]): { fetchFn: FetchFn; calls: Call[] } {
  const calls: Call[] = [];
  const fetchFn: FetchFn = (input, init) => {
    calls.push({
      method: init?.method ?? 'GET',
      url: String(input),
      headers: init?.headers as Record<string, string>,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    });
    const next = responses.shift() ?? { body: {} };
    return Promise.resolve(new Response(JSON.stringify(next.body), { status: next.status ?? 200 }));
  };
  return { fetchFn, calls };
}

describe('OllamaEmbedder', () => {
  it('batches documents and adds the document prefix', async () => {
    const { fetchFn, calls } = stubFetch({ body: { embeddings: [[1], [2]] } }, { body: { embeddings: [[3]] } });
    const embedder = new OllamaEmbedder({ baseUrl: 'http://ollama:11434/', model: 'nomic-embed-text', batchSize: 2, fetchFn });

    expect(await embedder.embedDocuments(['a', 'b', 'c'])).toEqual([[1], [2], [3]]);
    expect(calls.map((c) => [c.method, c.url])).toEqual([
      ['POST', 'http://ollama:11434/api/embed'],
      ['POST', 'http://ollama:11434/api/embed'],
    ]);
    expect(calls[0]?.body).toEqual({ model: 'nomic-embed-text', input: ['search_document: a', 'search_document: b'], truncate: true });
  });

  it('adds the query prefix to questions', async () => {
    const { fetchFn, calls } = stubFetch({ body: { embeddings: [[0.5]] } });
    const embedder = new OllamaEmbedder({ baseUrl: 'http://ollama:11434', model: 'm', fetchFn });
    expect(await embedder.embedQuery('why?')).toEqual([0.5]);
    expect(calls[0]?.body).toMatchObject({ input: ['search_query: why?'] });
  });

  it('turns HTTP errors and malformed answers into UpstreamError', async () => {
    const failing = new OllamaEmbedder({
      baseUrl: 'http://ollama:11434',
      model: 'm',
      fetchFn: stubFetch({ status: 404, body: { error: 'model not found' } }).fetchFn,
    });
    await expect(failing.embedDocuments(['x'])).rejects.toMatchObject({ name: 'UpstreamError', service: 'ollama', status: 404 });

    const short = new OllamaEmbedder({ baseUrl: 'http://ollama:11434', model: 'm', fetchFn: stubFetch({ body: { embeddings: [] } }).fetchFn });
    await expect(short.embedDocuments(['x'])).rejects.toThrow('expected 1 embeddings, received 0');
  });

  it('reports an unreachable service', async () => {
    const fetchFn: FetchFn = () => Promise.reject(new TypeError('fetch failed'));
    const embedder = new OllamaEmbedder({ baseUrl: 'http://ollama:11434', model: 'm', fetchFn });
    await expect(embedder.health()).rejects.toThrow('ollama: request to /api/version failed: fetch failed');
  });
});

describe('QdrantStore', () => {
  const options = { baseUrl: 'http://qdrant:6333', apiKey: 'secret', collection: 'notes' };

  it('creates a missing collection with its payload indexes, sending the API key', async () => {
    const { fetchFn, calls } = stubFetch({ body: { result: { exists: false } } });
    await new QdrantStore({ ...options, fetchFn }).ensureCollection(768);

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'GET http://qdrant:6333/collections/notes/exists',
      'PUT http://qdrant:6333/collections/notes',
      'PUT http://qdrant:6333/collections/notes/index?wait=true',
      'PUT http://qdrant:6333/collections/notes/index?wait=true',
      'PUT http://qdrant:6333/collections/notes/index?wait=true',
    ]);
    expect(calls[1]?.body).toEqual({ vectors: { size: 768, distance: 'Cosine' } });
    expect(calls.slice(2).map((c) => c.body)).toEqual([
      { field_name: 'path', field_schema: 'keyword' },
      { field_name: 'tags', field_schema: 'keyword' },
      { field_name: 'chunk_index', field_schema: 'integer' },
    ]);
    expect(calls.every((c) => c.headers['api-key'] === 'secret')).toBe(true);
  });

  it('refuses an existing collection with another vector size', async () => {
    const { fetchFn } = stubFetch(
      { body: { result: { exists: true } } },
      { body: { result: { config: { params: { vectors: { size: 384 } } } } } },
    );
    await expect(new QdrantStore({ ...options, fetchFn }).ensureCollection(768)).rejects.toThrow(/size 384.*produces 768/);
  });

  it('pages through the first chunks to list indexed notes', async () => {
    const { fetchFn, calls } = stubFetch(
      {
        body: {
          result: {
            points: [{ payload: { path: 'a.md', note_hash: 'h1', index_version: 'v' } }],
            next_page_offset: 'next-id',
          },
        },
      },
      { body: { result: { points: [{ payload: { path: 'b.md', note_hash: 'h2', index_version: 'v' } }], next_page_offset: null } } },
    );

    expect(await new QdrantStore({ ...options, fetchFn }).listIndexedNotes()).toEqual([
      { path: 'a.md', hash: 'h1', version: 'v' },
      { path: 'b.md', hash: 'h2', version: 'v' },
    ]);
    expect(calls[0]?.body).toMatchObject({ filter: { must: [{ key: 'chunk_index', match: { value: 0 } }] }, with_vector: false });
    expect(calls[1]?.body).toMatchObject({ offset: 'next-id' });
  });

  it('deletes a whole note or only its tail chunks', async () => {
    const { fetchFn, calls } = stubFetch({ body: {} }, { body: {} });
    const store = new QdrantStore({ ...options, fetchFn });
    await store.deleteNote('a.md');
    await store.deleteNote('a.md', 3);

    expect(calls[0]?.body).toEqual({ filter: { must: [{ key: 'path', match: { value: 'a.md' } }] } });
    expect(calls[1]?.body).toEqual({
      filter: {
        must: [
          { key: 'path', match: { value: 'a.md' } },
          { key: 'chunk_index', range: { gte: 3 } },
        ],
      },
    });
  });

  it('searches with tag filter and score threshold', async () => {
    const payload = { path: 'a.md', title: 'A' };
    const { fetchFn, calls } = stubFetch({ body: { result: { points: [{ score: 0.9, payload }] } } });

    const hits = await new QdrantStore({ ...options, fetchFn }).search([0.1, 0.2], { limit: 3, tags: ['ai'], minScore: 0.5 });

    expect(hits).toEqual([{ score: 0.9, payload }]);
    expect(calls[0]?.url).toBe('http://qdrant:6333/collections/notes/points/query');
    expect(calls[0]?.body).toEqual({
      query: [0.1, 0.2],
      limit: 3,
      with_payload: true,
      score_threshold: 0.5,
      filter: { must: [{ key: 'tags', match: { any: ['ai'] } }] },
    });
  });

  it('returns no result before the first ingestion (missing collection)', async () => {
    const { fetchFn } = stubFetch({ status: 404, body: { status: { error: 'Not found' } } });
    expect(await new QdrantStore({ ...options, fetchFn }).search([1], { limit: 5 })).toEqual([]);
  });

  it('surfaces authentication failures', async () => {
    const { fetchFn } = stubFetch({ status: 401, body: 'Invalid API key' });
    await expect(new QdrantStore({ ...options, fetchFn }).health()).rejects.toBeInstanceOf(UpstreamError);
  });
});
