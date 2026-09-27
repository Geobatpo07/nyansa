import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { join, posix, relative, sep } from 'node:path';

export interface VaultFile {
  /** Vault-relative POSIX path. */
  path: string;
  absolutePath: string;
}

export interface NoteContent {
  content: string;
  /** SHA-256 of the raw bytes. */
  hash: string;
  /** Obsidian writes UTF-8; imported files are sometimes Windows-1252. */
  encoding: 'utf-8' | 'windows-1252';
}

const utf8 = new TextDecoder('utf-8', { fatal: true });
const windows1252 = new TextDecoder('windows-1252');

// Non-hidden folders that never hold notes. Hidden ones (Obsidian and sync
// tool data) are skipped by name.
const IGNORED_DIRECTORIES = new Set(['node_modules']);

/**
 * Lists every Markdown note of the vault, sorted by path. Hidden entries
 * (`.obsidian`, `.trash`, `.stfolder`, dotfiles) are skipped.
 */
export async function listNotes(root: string): Promise<VaultFile[]> {
  const files: VaultFile[] = [];

  async function walk(directory: string): Promise<void> {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name.startsWith('.')) {
        continue;
      }
      const absolutePath = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!IGNORED_DIRECTORIES.has(entry.name)) {
          await walk(absolutePath);
        }
      } else if (entry.isFile() && entry.name.toLowerCase().endsWith('.md')) {
        files.push({ path: toPosix(relative(root, absolutePath)), absolutePath });
      }
    }
  }

  await walk(root);
  return files.sort((a, b) => a.path.localeCompare(b.path));
}

export async function readNote(file: VaultFile): Promise<NoteContent> {
  const bytes = await readFile(file.absolutePath);
  return { ...decode(bytes), hash: sha256(bytes) };
}

/** Decodes strict UTF-8 (BOM removed), falling back to Windows-1252 for invalid UTF-8. */
export function decode(bytes: Uint8Array): Pick<NoteContent, 'content' | 'encoding'> {
  try {
    return { content: utf8.decode(bytes), encoding: 'utf-8' };
  } catch {
    return { content: windows1252.decode(bytes), encoding: 'windows-1252' };
  }
}

export function sha256(data: string | Buffer): string {
  return createHash('sha256').update(data).digest('hex');
}

function toPosix(path: string): string {
  return path.split(sep).join(posix.sep);
}
