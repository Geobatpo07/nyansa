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
}

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
  return { content: bytes.toString('utf8'), hash: sha256(bytes) };
}

export function sha256(data: string | Buffer): string {
  return createHash('sha256').update(data).digest('hex');
}

function toPosix(path: string): string {
  return path.split(sep).join(posix.sep);
}
