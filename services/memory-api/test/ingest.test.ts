import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { embeddingText, IngestInProgressError, Ingestor, pointId } from '../src/ingest/ingest.js';
import { FakeEmbedder, InMemoryStore, silentLogger, TempVault } from './fakes.js';

describe('Ingestor', () => {
  let vault: TempVault;
  let embedder: FakeEmbedder;
  let store: InMemoryStore;
  let ingestor: Ingestor;

  beforeEach(async () => {
    vault = await TempVault.create();
    embedder = new FakeEmbedder();
    store = new InMemoryStore();
    ingestor = new Ingestor({
      vaultPath: vault.root,
      embedder,
      store,
      chunking: { maxChars: 200 },
      logger: silentLogger,
      now: () => new Date('2026-09-26T12:00:00Z'),
    });
    await vault.write('Alpha.md', '---\ntags: [project]\n---\n# Alpha\nAlpha links to [[Beta]].\n## Details\nMore about alpha.');
    await vault.write('notes/Beta.md', '# Beta\nBeta content #idea');
    await vault.write('.obsidian/workspace.md', 'ignored');
    await vault.write('attachment.png', 'not a note');
  });

  afterEach(async () => {
    await vault.dispose();
  });

  it('indexes every note of an empty index with metadata', async () => {
    const report = await ingestor.run('incremental');

    expect(report.notes).toEqual({ scanned: 2, indexed: 2, unchanged: 0, deleted: 0, failed: 0 });
    expect(report.chunks.upserted).toBe(3);
    expect(store.notes()).toEqual({ 'Alpha.md': 2, 'notes/Beta.md': 1 });

    const details = store.points.get(pointId('Alpha.md', 1));
    expect(details?.payload).toMatchObject({
      path: 'Alpha.md',
      title: 'Alpha',
      tags: ['project'],
      links: ['Beta'],
      section: 'Alpha > Details',
      chunk_index: 1,
      chunk_count: 2,
      text: 'More about alpha.',
      index_version: ingestor.indexVersion,
      indexed_at: '2026-09-26T12:00:00.000Z',
    });
    expect(details?.payload.note_hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it('skips unchanged notes on the next incremental run', async () => {
    await ingestor.run('incremental');
    const embeddedBefore = embedder.documentsEmbedded;

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 0, unchanged: 2, deleted: 0 });
    // Only the dimension probe of the first run; nothing re-embedded.
    expect(embedder.documentsEmbedded).toBe(embeddedBefore);
  });

  it('reindexes a modified note and drops the chunks it no longer has', async () => {
    await ingestor.run('incremental');
    await vault.write('Alpha.md', '# Alpha\nShorter now.');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 1, unchanged: 1 });
    expect(store.notes()).toEqual({ 'Alpha.md': 1, 'notes/Beta.md': 1 });
    expect(store.points.get(pointId('Alpha.md', 0))?.payload.text).toBe('Shorter now.');
  });

  it('removes the points of deleted notes', async () => {
    await ingestor.run('incremental');
    await vault.remove('notes/Beta.md');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ scanned: 1, deleted: 1 });
    expect(store.notes()).toEqual({ 'Alpha.md': 2 });
  });

  it('reindexes everything in full mode', async () => {
    await ingestor.run('incremental');
    const report = await ingestor.run('full');
    expect(report.notes).toMatchObject({ indexed: 2, unchanged: 0 });
  });

  it('reindexes notes indexed with another version (chunking or model change)', async () => {
    await ingestor.run('incremental');
    const other = new Ingestor({
      vaultPath: vault.root,
      embedder,
      store,
      chunking: { maxChars: 500 },
      logger: silentLogger,
    });
    expect(other.indexVersion).not.toBe(ingestor.indexVersion);
    expect((await other.run('incremental')).notes.indexed).toBe(2);
  });

  it('keeps the previous version of a note when its embedding fails', async () => {
    await ingestor.run('incremental');
    await vault.write('notes/Beta.md', '# Beta\nPOISON');
    embedder.failOn = (text) => text.includes('POISON');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 0, failed: 1 });
    expect(report.errors).toEqual([{ path: 'notes/Beta.md', message: 'embedding failed' }]);
    expect(store.points.get(pointId('notes/Beta.md', 0))?.payload.text).toBe('Beta content #idea');
    // A later run retries it because its hash still differs.
    embedder.failOn = undefined;
    expect((await ingestor.run('incremental')).notes.indexed).toBe(1);
  });

  it('refuses a second run while one is in progress', async () => {
    const first = ingestor.run('full');
    await expect(ingestor.run('full')).rejects.toBeInstanceOf(IngestInProgressError);
    await first;
    expect(ingestor.isRunning).toBe(false);
  });
});

describe('pointId', () => {
  it('is a deterministic RFC 4122 UUID per path and chunk', () => {
    const id = pointId('a.md', 0);
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(pointId('a.md', 0)).toBe(id);
    expect(pointId('a.md', 1)).not.toBe(id);
    expect(pointId('b.md', 0)).not.toBe(id);
  });
});

describe('embeddingText', () => {
  it('prefixes the chunk with its title and section', () => {
    expect(embeddingText({ title: 'Note' }, 'A > B', 'text')).toBe('Note > A > B\n\ntext');
    expect(embeddingText({ title: 'Note' }, '', 'text')).toBe('Note\n\ntext');
  });
});
