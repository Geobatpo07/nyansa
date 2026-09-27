import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { decode, listNotes, readNote } from '../src/vault/vault.js';
import { TempVault } from './fakes.js';

describe('decode', () => {
  it('reads UTF-8 and drops the byte order mark', () => {
    expect(decode(Buffer.from('﻿Café 東京 🚀', 'utf8'))).toEqual({ content: 'Café 東京 🚀', encoding: 'utf-8' });
  });

  it('falls back to Windows-1252 for invalid UTF-8', () => {
    // "Café – 5 €" in Windows-1252: é = 0xE9, en dash = 0x96, euro = 0x80.
    const bytes = Buffer.from([0x43, 0x61, 0x66, 0xe9, 0x20, 0x96, 0x20, 0x35, 0x20, 0x80]);
    expect(decode(bytes)).toEqual({ content: 'Café – 5 €', encoding: 'windows-1252' });
  });
});

describe('listNotes and readNote', () => {
  let vault: TempVault;

  beforeEach(async () => {
    vault = await TempVault.create();
  });

  afterEach(async () => {
    await vault.dispose();
  });

  it('lists Markdown notes with POSIX paths, skipping hidden folders and other files', async () => {
    await vault.write('b.md', 'b');
    await vault.write('dir/sub/A.MD', 'a');
    await vault.write('.obsidian/config.md', 'x');
    await vault.write('.trash/old.md', 'x');
    await vault.write('node_modules/pkg/readme.md', 'x');
    await vault.write('image.png', 'x');

    expect((await listNotes(vault.root)).map((file) => file.path)).toEqual(['b.md', 'dir/sub/A.MD']);
  });

  it('hashes the raw bytes', async () => {
    await vault.write('n.md', 'same');
    const [file] = await listNotes(vault.root);
    const first = await readNote(file as NonNullable<typeof file>);
    await vault.write('n.md', 'same ');
    const second = await readNote(file as NonNullable<typeof file>);
    expect(first.hash).toMatch(/^[0-9a-f]{64}$/);
    expect(second.hash).not.toBe(first.hash);
  });
});
