import { timingSafeEqual } from 'node:crypto';

import Fastify, { type FastifyBaseLogger, type FastifyInstance } from 'fastify';
import { z } from 'zod';

import { IngestInProgressError, type Ingestor } from './ingest/ingest.js';
import { UpstreamError, type Embedder, type VectorStore } from './ports.js';
import type { SearchService } from './search/search.js';

export interface AppDeps {
  token: string;
  ingestor: Pick<Ingestor, 'run' | 'isRunning'>;
  search: Pick<SearchService, 'search'>;
  embedder: Pick<Embedder, 'health'>;
  store: Pick<VectorStore, 'health'>;
  /** Shared with the ingestor; logging is off when omitted (tests). */
  logger?: FastifyBaseLogger;
}

const IngestBody = z
  .object({
    mode: z.enum(['full', 'incremental']).default('incremental'),
  })
  .strict();

const SearchBody = z
  .object({
    query: z.string().trim().min(1).max(2000),
    limit: z.number().int().min(1).max(50).default(5),
    tags: z.array(z.string().min(1)).max(20).optional(),
    minScore: z.number().min(-1).max(1).optional(),
  })
  .strict();

/** Builds the HTTP API. Dependencies are injected so tests can replace them. */
export function buildApp(deps: AppDeps): FastifyInstance {
  const app = Fastify({
    bodyLimit: 64 * 1024,
    ...(deps.logger === undefined ? { logger: false } : { loggerInstance: deps.logger }),
  });
  const expectedToken = Buffer.from(deps.token);

  // Accept `content-type: application/json` with an empty body (the /ingest
  // body is optional, and some clients always send the header).
  app.removeContentTypeParser('application/json');
  app.addContentTypeParser('application/json', { parseAs: 'string' }, (_request, body, done) => {
    const text = typeof body === 'string' ? body : body.toString('utf8');
    if (text.trim() === '') {
      done(null, undefined);
      return;
    }
    try {
      done(null, JSON.parse(text));
    } catch {
      done(Object.assign(new Error('invalid JSON body'), { statusCode: 400 }), undefined);
    }
  });

  // Every route except /health needs `Authorization: Bearer <MEMORY_API_TOKEN>`.
  app.addHook('onRequest', async (request, reply) => {
    if (request.routeOptions.url === '/health') {
      return;
    }
    const header = request.headers.authorization ?? '';
    const provided = Buffer.from(header.startsWith('Bearer ') ? header.slice(7) : '');
    if (provided.length !== expectedToken.length || !timingSafeEqual(provided, expectedToken)) {
      return reply.code(401).send({ error: 'unauthorized' });
    }
  });

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof z.ZodError) {
      return reply.code(400).send({
        error: 'invalid request',
        issues: error.issues.map((issue) => ({ path: issue.path.join('.'), message: issue.message })),
      });
    }
    if (error instanceof IngestInProgressError) {
      return reply.code(409).send({ error: error.message });
    }
    if (error instanceof UpstreamError) {
      request.log.error({ err: error }, 'upstream failure');
      return reply.code(502).send({ error: 'upstream service failure', service: error.service, detail: error.message });
    }
    const status = (error as { statusCode?: number }).statusCode;
    if (status !== undefined && status >= 400 && status < 500) {
      return reply.code(status).send({ error: (error as Error).message });
    }
    request.log.error({ err: error }, 'unhandled error');
    return reply.code(500).send({ error: 'internal error' });
  });

  app.get('/health', async (_request, reply) => {
    const [ollama, qdrant] = await Promise.all([check(() => deps.embedder.health()), check(() => deps.store.health())]);
    const ok = ollama === 'ok' && qdrant === 'ok';
    return reply.code(ok ? 200 : 503).send({
      status: ok ? 'ok' : 'degraded',
      checks: { ollama, qdrant },
      ingesting: deps.ingestor.isRunning,
    });
  });

  app.post('/ingest', async (request) => {
    const { mode } = IngestBody.parse(request.body ?? {});
    return deps.ingestor.run(mode);
  });

  app.post('/search', async (request) => {
    const body = SearchBody.parse(request.body);
    const results = await deps.search.search({
      query: body.query,
      limit: body.limit,
      ...(body.tags === undefined ? {} : { tags: body.tags }),
      ...(body.minScore === undefined ? {} : { minScore: body.minScore }),
    });
    return { query: body.query, results };
  });

  return app;
}

async function check(probe: () => Promise<void>): Promise<string> {
  try {
    await probe();
    return 'ok';
  } catch (err) {
    return err instanceof Error ? err.message : String(err);
  }
}
