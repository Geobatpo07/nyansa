import re

from src.vault import decode, list_notes, read_note
from tests.fakes import Vault


def test_decode_reads_utf8_and_drops_the_byte_order_mark() -> None:
    assert decode("﻿Café 東京 🚀".encode()) == ("Café 東京 🚀", "utf-8")


def test_decode_falls_back_to_windows_1252_for_invalid_utf8() -> None:
    # "Café – 5 €" in Windows-1252: é = 0xE9, en dash = 0x96, euro = 0x80.
    assert decode(bytes([0x43, 0x61, 0x66, 0xE9, 0x20, 0x96, 0x20, 0x35, 0x20, 0x80])) == ("Café – 5 €", "windows-1252")


def test_decode_keeps_the_bytes_windows_1252_leaves_undefined() -> None:
    assert decode(bytes([0x41, 0x81, 0x8D, 0xE9])) == ("A\x81\x8dé", "windows-1252")


def test_lists_markdown_notes_with_posix_paths_skipping_hidden_folders_and_other_files(vault: Vault) -> None:
    for path in [
        "b.md",
        "dir/sub/A.MD",
        ".obsidian/config.md",
        ".trash/old.md",
        "node_modules/pkg/readme.md",
        "image.png",
    ]:
        vault.write(path, "x")
    assert list_notes(vault.root) == ["b.md", "dir/sub/A.MD"]


def test_hashes_the_raw_bytes(vault: Vault) -> None:
    vault.write("n.md", "same")
    first = read_note(vault.root, "n.md")
    vault.write("n.md", "same ")
    second = read_note(vault.root, "n.md")
    assert re.fullmatch(r"[0-9a-f]{64}", first.hash)
    assert second.hash != first.hash
