import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { embeddingText, IngestInProgressError, Ingestor, pointId } from '../src/ingest/ingest.js';
import { UpstreamError } from '../src/ports.js';
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

    expect(report.notes).toEqual({ scanned: 2, indexed: 2, unchanged: 0, deleted: 0, failed: 0, skipped: 0 });
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

  it('reindexes a shortened note and drops the chunks it no longer has', async () => {
    await ingestor.run('incremental');
    expect(store.points.has(pointId('Alpha.md', 1))).toBe(true);
    await vault.write('Alpha.md', '# Alpha\nShorter now.');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 1, unchanged: 1 });
    expect(store.notes()).toEqual({ 'Alpha.md': 1, 'notes/Beta.md': 1 });
    expect(store.points.get(pointId('Alpha.md', 0))?.payload).toMatchObject({ text: 'Shorter now.', chunk_count: 1 });
    expect(store.points.has(pointId('Alpha.md', 1))).toBe(false);
  });

  it('removes every chunk of a deleted note', async () => {
    await vault.write('Long.md', `# Long\n${'First part. '.repeat(20)}\n## Two\n${'Second part. '.repeat(20)}`);
    await ingestor.run('incremental');
    const longIds = [0, 1, 2].map((i) => pointId('Long.md', i)).filter((id) => store.points.has(id));
    expect(longIds.length).toBeGreaterThan(1);
    await vault.remove('Long.md');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ scanned: 2, deleted: 1 });
    expect(longIds.some((id) => store.points.has(id))).toBe(false);
    expect(store.notes()).toEqual({ 'Alpha.md': 2, 'notes/Beta.md': 1 });
  });

  it('moves a renamed note: old path removed, new path indexed', async () => {
    await ingestor.run('incremental');
    const oldIds = [pointId('notes/Beta.md', 0)];
    await vault.remove('notes/Beta.md');
    await vault.write('archive/Beta renamed.md', '# Beta\nBeta content #idea');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 1, deleted: 1, unchanged: 1 });
    expect(oldIds.some((id) => store.points.has(id))).toBe(false);
    expect(store.notes()).toEqual({ 'Alpha.md': 2, 'archive/Beta renamed.md': 1 });
    expect(store.points.get(pointId('archive/Beta renamed.md', 0))?.payload.path).toBe('archive/Beta renamed.md');
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

  it('stops early when the embedding service is down, and resumes on the next run', async () => {
    await ingestor.run('incremental');
    const alphaHashBefore = (await store.listIndexedNotes()).find((n) => n.path === 'Alpha.md')?.hash;
    // Sorted before the new notes, so it is among the failed ones.
    await vault.write('Alpha.md', '# Alpha\nEdited while Ollama is down.');
    for (let i = 0; i < 6; i++) {
      await vault.write(`batch/note-${i}.md`, `# Note ${i}\ncontent ${i}`);
    }
    const embed = embedder.embedDocuments.bind(embedder);
    embedder.embedDocuments = () => Promise.reject(new UpstreamError('ollama', 'request to /api/embed failed: fetch failed'));

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ indexed: 0, failed: 3, skipped: 4, unchanged: 1 });
    expect(report.aborted).toBe('3 consecutive failures of ollama; 4 notes skipped, retried on the next run');

    // No hash is recorded for the notes that failed or were skipped: new
    // notes are absent from the index, the edited note keeps its old hash.
    const indexed = new Map((await store.listIndexedNotes()).map((n) => [n.path, n.hash]));
    expect([...indexed.keys()].filter((path) => path.startsWith('batch/'))).toEqual([]);
    expect(indexed.get('Alpha.md')).toBe(alphaHashBefore);

    embedder.embedDocuments = embed;
    const retry = await ingestor.run('incremental');
    expect(retry.notes).toMatchObject({ indexed: 7, failed: 0, skipped: 0, unchanged: 1 });
    expect(retry.aborted).toBeUndefined();
    expect(store.points.get(pointId('Alpha.md', 0))?.payload.text).toBe('Edited while Ollama is down.');
    expect(Object.keys(store.notes()).filter((path) => path.startsWith('batch/'))).toHaveLength(6);
  });

  it('does not stop on failures specific to each note', async () => {
    await ingestor.run('incremental');
    for (let i = 0; i < 5; i++) {
      await vault.write(`bad/note-${i}.md`, `# Bad ${i}\nPOISON`);
    }
    embedder.failOn = (text) => text.includes('POISON');

    const report = await ingestor.run('incremental');

    expect(report.notes).toMatchObject({ failed: 5, skipped: 0 });
    expect(report.aborted).toBeUndefined();
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
