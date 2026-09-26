import { describe, expect, it } from 'vitest';

import { loadConfig } from '../src/config.js';

const required = { MEMORY_API_TOKEN: 'a'.repeat(32), QDRANT_API_KEY: 'key' };

describe('loadConfig', () => {
  it('applies defaults for the Docker network', () => {
    expect(loadConfig(required)).toMatchObject({
      MEMORY_API_PORT: 8080,
      VAULT_PATH: '/vault',
      OLLAMA_URL: 'http://nyansa-ollama:11434',
      EMBEDDING_MODEL: 'nomic-embed-text',
      QDRANT_URL: 'http://nyansa-qdrant:6333',
      QDRANT_COLLECTION: 'obsidian_notes',
      CHUNK_MAX_CHARS: 1500,
    });
  });

  it('coerces numeric variables', () => {
    expect(loadConfig({ ...required, MEMORY_API_PORT: '9000', CHUNK_MAX_CHARS: '800' })).toMatchObject({
      MEMORY_API_PORT: 9000,
      CHUNK_MAX_CHARS: 800,
    });
  });

  it('lists every invalid variable', () => {
    expect(() => loadConfig({ MEMORY_API_TOKEN: 'short', QDRANT_URL: 'not a url', CHUNK_MAX_CHARS: '10' })).toThrow(
      /MEMORY_API_TOKEN: MEMORY_API_TOKEN must be at least 32 characters[\s\S]*QDRANT_URL[\s\S]*QDRANT_API_KEY[\s\S]*CHUNK_MAX_CHARS/,
    );
  });
});
