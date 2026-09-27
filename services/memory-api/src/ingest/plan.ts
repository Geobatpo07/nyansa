import type { IndexedNote } from '../domain.js';

export type IngestMode = 'full' | 'incremental';

export interface NoteFingerprint {
  path: string;
  hash: string;
}

export interface IngestPlan {
  /** Notes to (re)index: new, modified, or indexed with another index version. */
  toIndex: string[];
  /** Notes whose content and index version did not change. */
  unchanged: string[];
  /** Notes present in the index but no longer in the vault. */
  toDelete: string[];
}

/**
 * Decides what an ingestion run must do. Pure function: the vault and the
 * index are passed in, nothing is read or written.
 *
 * - full: every vault note is reindexed.
 * - incremental: only notes whose hash or index version differ from the
 *   index are reindexed.
 * In both modes, notes deleted from the vault are removed from the index.
 */
export function planIngest(
  vault: NoteFingerprint[],
  indexed: IndexedNote[],
  mode: IngestMode,
  indexVersion: string,
): IngestPlan {
  const known = new Map(indexed.map((note) => [note.path, note]));
  const inVault = new Set(vault.map((note) => note.path));

  const toIndex: string[] = [];
  const unchanged: string[] = [];
  for (const note of vault) {
    const previous = known.get(note.path);
    const upToDate = previous !== undefined && previous.hash === note.hash && previous.version === indexVersion;
    if (mode === 'incremental' && upToDate) {
      unchanged.push(note.path);
    } else {
      toIndex.push(note.path);
    }
  }

  const toDelete = [...known.keys()].filter((path) => !inVault.has(path)).sort((a, b) => a.localeCompare(b));
  return { toIndex, unchanged, toDelete };
}
