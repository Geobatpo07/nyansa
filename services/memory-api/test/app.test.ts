import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { buildApp } from '../src/app.js';
import { Ingestor } from '../src/ingest/ingest.js';
import { UpstreamError } from '../src/ports.js';
import { SearchService } from '../src/search/search.js';
import { FakeEmbedder, InMemoryStore, silentLogger, TempVault } from './fakes.js';

const TOKEN = 't'.repeat(32);
const auth = { authorization: `Bearer ${TOKEN}` };

describe('HTTP API', () => {
  let vault: TempVault;
  let embedder: FakeEmbedder;
  let store: InMemoryStore;
  let app: ReturnType<typeof buildApp>;

  beforeEach(async () => {
    vault = await TempVault.create();
    await vault.write('Docker.md', '---\ntags: [infra]\n---\n# Docker\n## Compose\nDocker compose runs the stack with profiles.');
    await vault.write('Cooking.md', '# Cooking\nA recipe for bread with flour and water.');
    embedder = new FakeEmbedder();
    store = new InMemoryStore();
    const ingestor = new Ingestor({ vaultPath: vault.root, embedder, store, chunking: { maxChars: 500 }, logger: silentLogger });
    app = buildApp({ token: TOKEN, ingestor, search: new SearchService(embedder, store), embedder, store });
  });

  afterEach(async () => {
    await app.close();
    await vault.dispose();
  });

  describe('authentication', () => {
    it.each([
      ['no header', {}],
      ['wrong token', { authorization: `Bearer ${'x'.repeat(32)}` }],
      ['wrong scheme', { authorization: `Basic ${TOKEN}` }],
    ])('rejects %s', async (_label, headers) => {
      const response = await app.inject({ method: 'POST', url: '/search', headers, payload: { query: 'x' } });
      expect(response.statusCode).toBe(401);
    });

    it('leaves /health open', async () => {
      expect((await app.inject({ method: 'GET', url: '/health?probe=1' })).statusCode).toBe(200);
    });
  });

  it('GET /health reports each dependency', async () => {
    const response = await app.inject({ method: 'GET', url: '/health' });
    expect(response.json()).toEqual({ status: 'ok', checks: { ollama: 'ok', qdrant: 'ok' }, ingesting: false });
  });

  it('GET /health is 503 when a dependency is down', async () => {
    store.health = () => Promise.reject(new UpstreamError('qdrant', 'HTTP 401 on /collections'));
    const response = await app.inject({ method: 'GET', url: '/health' });
    expect(response.statusCode).toBe(503);
    expect(response.json()).toMatchObject({ status: 'degraded', checks: { ollama: 'ok', qdrant: 'qdrant: HTTP 401 on /collections' } });
  });

  it('POST /ingest runs an incremental ingestion by default', async () => {
    const response = await app.inject({ method: 'POST', url: '/ingest', headers: auth });
    expect(response.statusCode).toBe(200);
    expect(response.json()).toMatchObject({ mode: 'incremental', notes: { scanned: 2, indexed: 2 } });

    const again = await app.inject({ method: 'POST', url: '/ingest', headers: auth, payload: { mode: 'full' } });
    expect(again.json()).toMatchObject({ mode: 'full', notes: { indexed: 2, unchanged: 0 } });
  });

  it('POST /ingest validates the mode', async () => {
    const response = await app.inject({ method: 'POST', url: '/ingest', headers: auth, payload: { mode: 'everything' } });
    expect(response.statusCode).toBe(400);
    expect(response.json()).toMatchObject({ error: 'invalid request', issues: [{ path: 'mode' }] });
  });

  it('POST /ingest answers 409 while an ingestion runs', async () => {
    const first = app.inject({ method: 'POST', url: '/ingest', headers: auth });
    const second = app.inject({ method: 'POST', url: '/ingest', headers: auth });
    const statuses = (await Promise.all([first, second])).map((r) => r.statusCode).sort((a, b) => a - b);
    expect(statuses).toEqual([200, 409]);
  });

  it('POST /search returns ranked chunks with their source note', async () => {
    await app.inject({ method: 'POST', url: '/ingest', headers: auth });

    const response = await app.inject({ method: 'POST', url: '/search', headers: auth, payload: { query: 'docker compose stack', limit: 1 } });

    expect(response.statusCode).toBe(200);
    const body = response.json<{ query: string; results: Record<string, unknown>[] }>();
    expect(body.query).toBe('docker compose stack');
    expect(body.results).toHaveLength(1);
    expect(body.results[0]).toMatchObject({
      path: 'Docker.md',
      title: 'Docker',
      section: 'Docker > Compose',
      tags: ['infra'],
      chunkIndex: 0,
      text: 'Docker compose runs the stack with profiles.',
    });
    expect(body.results[0]?.['score']).toBeGreaterThan(0);
  });

  it('POST /search filters by tag (with or without #)', async () => {
    await app.inject({ method: 'POST', url: '/ingest', headers: auth });
    const response = await app.inject({ method: 'POST', url: '/search', headers: auth, payload: { query: 'bread recipe', tags: ['#INFRA'] } });
    const paths = response.json<{ results: { path: string }[] }>().results.map((r) => r.path);
    expect(paths).toEqual(['Docker.md']);
  });

  it('POST /search validates its body', async () => {
    for (const payload of [{}, { query: '   ' }, { query: 'x', limit: 0 }, { query: 'x', limit: 51 }, { query: 'x', extra: true }]) {
      const response = await app.inject({ method: 'POST', url: '/search', headers: auth, payload });
      expect(response.statusCode, JSON.stringify(payload)).toBe(400);
    }
  });

  it('maps upstream failures to 502', async () => {
    embedder.embedQuery = () => Promise.reject(new UpstreamError('ollama', 'HTTP 404 on /api/embed: model not found', 404));
    const response = await app.inject({ method: 'POST', url: '/search', headers: auth, payload: { query: 'x' } });
    expect(response.statusCode).toBe(502);
    expect(response.json()).toMatchObject({ service: 'ollama' });
  });

  it('rejects malformed JSON with 400', async () => {
    const response = await app.inject({
      method: 'POST',
      url: '/search',
      headers: { ...auth, 'content-type': 'application/json' },
      payload: '{"query":',
    });
    expect(response.statusCode).toBe(400);
  });
});
