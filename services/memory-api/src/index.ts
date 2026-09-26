import { pino } from 'pino';

import { buildApp } from './app.js';
import { OllamaEmbedder } from './clients/ollama.js';
import { QdrantStore } from './clients/qdrant.js';
import { loadConfig } from './config.js';
import { Ingestor } from './ingest/ingest.js';
import { SearchService } from './search/search.js';

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = pino({ level: config.LOG_LEVEL, redact: ['req.headers.authorization'] });

  const embedder = new OllamaEmbedder({ baseUrl: config.OLLAMA_URL, model: config.EMBEDDING_MODEL });
  const store = new QdrantStore({
    baseUrl: config.QDRANT_URL,
    apiKey: config.QDRANT_API_KEY,
    collection: config.QDRANT_COLLECTION,
  });
  const ingestor = new Ingestor({
    vaultPath: config.VAULT_PATH,
    embedder,
    store,
    chunking: { maxChars: config.CHUNK_MAX_CHARS },
    logger,
  });

  const app = buildApp({
    token: config.MEMORY_API_TOKEN,
    ingestor,
    search: new SearchService(embedder, store),
    embedder,
    store,
    logger,
  });

  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.once(signal, () => {
      logger.info({ signal }, 'shutting down');
      app.close().then(
        () => process.exit(0),
        () => process.exit(1),
      );
    });
  }

  await app.listen({ host: config.MEMORY_API_HOST, port: config.MEMORY_API_PORT });
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
