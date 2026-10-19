import pytest

from memory_api.config import load_config

REQUIRED = {"MEMORY_API_TOKEN": "a" * 32, "QDRANT_API_KEY": "key"}


def test_applies_defaults_for_the_docker_network() -> None:
    config = load_config(REQUIRED)
    assert (config.MEMORY_API_PORT, config.VAULT_PATH, config.CHUNK_MAX_CHARS) == (8080, "/vault", 1500)
    assert (config.OLLAMA_URL, config.QDRANT_URL) == ("http://nyansa-ollama:11434", "http://nyansa-qdrant:6333")
    assert (config.EMBEDDING_MODEL, config.QDRANT_COLLECTION) == ("nomic-embed-text", "obsidian_notes")


def test_coerces_numeric_variables_and_ignores_unrelated_ones() -> None:
    config = load_config({**REQUIRED, "MEMORY_API_PORT": "9000", "CHUNK_MAX_CHARS": "800", "PATH": "/usr/bin"})
    assert (config.MEMORY_API_PORT, config.CHUNK_MAX_CHARS) == (9000, 800)


def test_lists_every_invalid_variable() -> None:
    with pytest.raises(ValueError, match="invalid configuration") as raised:
        load_config({"MEMORY_API_TOKEN": "short", "QDRANT_URL": "not a url", "CHUNK_MAX_CHARS": "10"})
    for name in ("MEMORY_API_TOKEN", "QDRANT_URL", "QDRANT_API_KEY", "CHUNK_MAX_CHARS"):
        assert f"\n  - {name}: " in str(raised.value)
