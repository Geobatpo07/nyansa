import { z } from 'zod';

const ConfigSchema = z.object({
  MEMORY_API_HOST: z.string().default('0.0.0.0'),
  MEMORY_API_PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  /** Bearer token required on every route except /health. */
  MEMORY_API_TOKEN: z.string().min(32, 'MEMORY_API_TOKEN must be at least 32 characters'),
  VAULT_PATH: z.string().min(1).default('/vault'),
  OLLAMA_URL: z.url().default('http://nyansa-ollama:11434'),
  EMBEDDING_MODEL: z.string().min(1).default('nomic-embed-text'),
  QDRANT_URL: z.url().default('http://nyansa-qdrant:6333'),
  QDRANT_API_KEY: z.string().min(1, 'QDRANT_API_KEY is required'),
  QDRANT_COLLECTION: z.string().regex(/^[\w-]+$/).default('obsidian_notes'),
  CHUNK_MAX_CHARS: z.coerce.number().int().min(200).max(8000).default(1500),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent']).default('info'),
});

export type Config = z.infer<typeof ConfigSchema>;

/** Reads and validates the configuration; throws with every problem listed. */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const result = ConfigSchema.safeParse(env);
  if (!result.success) {
    const problems = result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`);
    throw new Error(`invalid configuration:\n  - ${problems.join('\n  - ')}`);
  }
  return result.data;
}
