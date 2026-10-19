"""Reads the Markdown notes of the vault."""

import codecs
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type Encoding = Literal["utf-8", "windows-1252"]

# Non-hidden folders that never hold notes. Hidden ones (Obsidian and sync
# tool data) are skipped by name.
_IGNORED_DIRECTORIES = {"node_modules"}


@dataclass(frozen=True)
class NoteFile:
    # Vault-relative POSIX path.
    path: str
    content: str
    # SHA-256 of the raw bytes.
    hash: str
    # Obsidian writes UTF-8; imported files are sometimes Windows-1252.
    encoding: Encoding


def list_notes(root: str | Path) -> list[str]:
    """Lists the vault-relative POSIX paths of every Markdown note, sorted.

    Hidden entries (`.obsidian`, `.trash`, `.stfolder`, dotfiles) are skipped;
    symbolic links are not followed.
    """
    root = Path(root)
    paths: list[str] = []

    def walk(directory: Path) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _IGNORED_DIRECTORIES:
                        walk(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".md"):
                    paths.append(Path(entry.path).relative_to(root).as_posix())

    walk(root)
    return sorted(paths)


def read_note(root: str | Path, path: str) -> NoteFile:
    data = (Path(root) / path).read_bytes()
    content, encoding = decode(data)
    return NoteFile(path, content, sha256(data), encoding)


def read_vault(root: str | Path) -> list[NoteFile]:
    return [read_note(root, path) for path in list_notes(root)]


def decode(data: bytes) -> tuple[str, Encoding]:
    """Decodes strict UTF-8 (byte order mark removed), falling back to Windows-1252."""
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="nyansa-c1-controls"), "windows-1252"


def _c1_controls(error: UnicodeError) -> tuple[str, int]:
    # The 5 bytes Windows-1252 leaves undefined become the C1 control with the
    # same code, as browsers (and the WHATWG encoding standard) decode them.
    if not isinstance(error, UnicodeDecodeError):
        raise error
    return error.object[error.start : error.end].decode("latin-1"), error.end


codecs.register_error("nyansa-c1-controls", _c1_controls)


def sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()
