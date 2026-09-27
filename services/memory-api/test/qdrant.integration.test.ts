// Runs the ingestion against a real Qdrant (the embeddings stay fake).
// Skipped unless QDRANT_TEST_URL is set, e.g.:
//   docker run -d --rm -p 127.0.0.1:6399:6333 -e QDRANT__SERVICE__API_KEY=test qdrant/qdrant:v1.19.1
//   QDRANT_TEST_URL=http://127.0.0.1:6399 QDRANT_TEST_API_KEY=test npm test
import { randomUUID } from 'node:crypto';

import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';

import { QdrantStore } from '../src/clients/qdrant.js';
import { Ingestor, pointId } from '../src/ingest/ingest.js';
import { UpstreamError } from '../src/ports.js';
import { FakeEmbedder, silentLogger, TempVault } from './fakes.js';

const url = process.env['QDRANT_TEST_URL'];
const apiKey = process.env['QDRANT_TEST_API_KEY'] ?? '';

describe.skipIf(url === undefined)('ingestion against a real Qdrant', () => {
  const collection = `test_${randomUUID().replace(/-/g, '')}`;
  let store: QdrantStore;
  let vault: TempVault;
  let embedder: FakeEmbedder;
  let ingestor: Ingestor;

  /** Chunk ids stored in Qdrant, per note path. */
  async function pointsByPath(): Promise<Record<string, string[]>> {
    const response = await fetch(`${url}/collections/${collection}/points/scroll`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'api-key': apiKey },
      body: JSON.stringify({ limit: 1000, with_payload: ['path'], with_vector: false }),
    });
    const body = (await response.json()) as { result: { points: { id: string; payload: { path: string } }[] } };
    const byPath: Record<string, string[]> = {};
    for (const point of body.result.points) {
      (byPath[point.payload.path] ??= []).push(point.id);
    }
    return byPath;
  }

  beforeAll(async () => {
    store = new QdrantStore({ baseUrl: url as string, apiKey, collection });
    vault = await TempVault.create();
  });

  afterAll(async () => {
    await fetch(`${url}/collections/${collection}`, { method: 'DELETE', headers: { 'api-key': apiKey } });
    await vault.dispose();
  });

  beforeEach(() => {
    embedder = new FakeEmbedder();
    ingestor = new Ingestor({ vaultPath: vault.root, embedder, store, chunking: { maxChars: 200 }, logger: silentLogger });
  });

  it('indexes the vault', async () => {
    await vault.write('Long.md', `# Long\n${'First part. '.repeat(15)}\n## Two\n${'Second part. '.repeat(15)}\n## Three\nEnd.`);
    await vault.write('Keep.md', '# Keep\nStays.');
    await vault.write('Gone.md', `# Gone\n${'Deleted soon. '.repeat(20)}`);
    await vault.write('Old name.md', '# Moving\nThis note will be renamed.');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 4, failed: 0 });
    const points = await pointsByPath();
    expect(points['Long.md']?.length).toBeGreaterThanOrEqual(3);
    expect(points['Gone.md']?.length).toBeGreaterThanOrEqual(2);
  });

  it('removes stale chunks of shortened, deleted and renamed notes', async () => {
    const before = await pointsByPath();
    await vault.write('Long.md', '# Long\nNow short.');
    await vault.remove('Gone.md');
    await vault.remove('Old name.md');
    await vault.write('New name.md', '# Moving\nThis note will be renamed.');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 2, deleted: 2, unchanged: 1, failed: 0 });
    const after = await pointsByPath();
    expect(after['Long.md']).toEqual([pointId('Long.md', 0)]);
    expect(after['Gone.md']).toBeUndefined();
    expect(after['Old name.md']).toBeUndefined();
    expect(after['New name.md']).toEqual([pointId('New name.md', 0)]);
    expect(after['Keep.md']).toEqual(before['Keep.md']);
    const allIds = Object.values(after).flat();
    for (const stale of [...(before['Long.md'] ?? []).slice(1), ...(before['Gone.md'] ?? []), ...(before['Old name.md'] ?? [])]) {
      expect(allIds).not.toContain(stale);
    }
  });

  it('records no hash for notes skipped after an aborted run', async () => {
    const keepHash = (await store.listIndexedNotes()).find((note) => note.path === 'Keep.md')?.hash;
    // A first run (nothing changed) lets the ingestor check the collection
    // while the embedding service still answers.
    expect((await ingestor.run('incremental')).notes.indexed).toBe(0);
    await vault.write('Keep.md', '# Keep\nEdited during the outage.');
    for (let i = 0; i < 5; i++) {
      await vault.write(`outage/n${i}.md`, `# Outage ${i}\ntext ${i}`);
    }
    embedder.embedDocuments = () => Promise.reject(new UpstreamError('ollama', 'fetch failed'));

    const report = await ingestor.run('incremental');

    expect(report.aborted).toBeDefined();
    expect(report.notes.failed + report.notes.skipped).toBe(6);
    const indexed = new Map((await store.listIndexedNotes()).map((note) => [note.path, note.hash]));
    expect([...indexed.keys()].filter((path) => path.startsWith('outage/'))).toEqual([]);
    expect(indexed.get('Keep.md')).toBe(keepHash);

    const retry = await new Ingestor({ vaultPath: vault.root, embedder: new FakeEmbedder(), store, chunking: { maxChars: 200 }, logger: silentLogger }).run(
      'incremental',
    );
    expect(retry.notes).toMatchObject({ indexed: 6, failed: 0, skipped: 0 });
    expect(Object.keys(await pointsByPath()).filter((path) => path.startsWith('outage/'))).toHaveLength(5);
  });
});
