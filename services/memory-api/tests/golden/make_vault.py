"""Writes the golden test vault. Rerun only to change the corpus, then
regenerate golden.json with the TypeScript reference implementation."""

from pathlib import Path

ROOT = Path(__file__).parent / "vault"

LONG_SENTENCES = " ".join(f"Sentence number {i} has quite a few words in it." for i in range(40))
NOTES: dict[str, bytes] = {
    "Docker.md": (
        b'---\ntitle: Docker setup\ntags: [Infra, "#Self-Hosted"]\naliases: [compose]\n---\n'
        b"Intro with #homelab and [[Tailscale]].\n\n# Setup\nInstall Docker.\n\n## Compose\n"
        b"Run `docker compose up` with profiles. See [[Caddy#TLS|the proxy]].\n\n"
        b"```bash\n# not a heading\ndocker compose --profile cpu up -d\n```\n\n## Backups\nNightly, see ![[backup.png]].\n"
    ),
    "Long.md": f"# Long\n{LONG_SENTENCES}\n\n{'x' * 3500}\n\n## Tail\nEnd.\n".encode(),
    "Paragraphs.md": "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(12)).encode(),
    "Café/Été 2026.md": "# Été\nNotes de vacances à Montréal 🚀, #voyage/canada.\n\n## Budget\n5 € par jour.\n".encode(),
    "crlf.md": b"---\r\ntag: windows\r\n---\r\nLine one\r\n[[Link]]\r\n## Section\r\nLine two\r\n",
    "bom.md": "﻿# BOM note\nStarts with a byte order mark.\n".encode(),
    "latin1.md": "# Résumé\nCafé – 5 € par tasse.\n".encode("cp1252"),
    "broken.md": b"---\n: : :\n---\n# Still here #tag\nBody.\n",
    "empty.md": b"\n\n   \n",
    "headings.md": b"# A\n### A3\ntext\n## B2\ntext\n# C ##\n```\nunclosed fence\n",
    "tags.md": b"---\ntags: alpha, beta gamma\n---\nIssue #42, https://example.com/page#anchor, `#code`, real #Tag-One and #tag_two.\n",
}

for name, data in NOTES.items():
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
