import { UpstreamError, type Embedder } from '../ports.js';
import { requestJson, type FetchFn } from './http.js';

export interface OllamaEmbedderOptions {
  baseUrl: string;
  model: string;
  /** Texts sent per /api/embed call. */
  batchSize?: number;
  timeoutMs?: number;
  /**
   * Task prefixes. nomic-embed-text is trained with `search_document: ` and
   * `search_query: `; other models may need none.
   */
  documentPrefix?: string;
  queryPrefix?: string;
  fetchFn?: FetchFn;
}

interface EmbedResponse {
  embeddings?: number[][];
}

export class OllamaEmbedder implements Embedder {
  readonly model: string;
  private readonly baseUrl: string;
  private readonly batchSize: number;
  private readonly timeoutMs: number;
  private readonly documentPrefix: string;
  private readonly queryPrefix: string;
  private readonly fetchFn: FetchFn;

  constructor(options: OllamaEmbedderOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.model = options.model;
    this.batchSize = options.batchSize ?? 32;
    this.timeoutMs = options.timeoutMs ?? 120_000;
    this.documentPrefix = options.documentPrefix ?? 'search_document: ';
    this.queryPrefix = options.queryPrefix ?? 'search_query: ';
    this.fetchFn = options.fetchFn ?? fetch;
  }

  async embedDocuments(texts: string[]): Promise<number[][]> {
    const vectors: number[][] = [];
    for (let start = 0; start < texts.length; start += this.batchSize) {
      const batch = texts.slice(start, start + this.batchSize).map((text) => this.documentPrefix + text);
      vectors.push(...(await this.embed(batch)));
    }
    return vectors;
  }

  async embedQuery(text: string): Promise<number[]> {
    const [vector] = await this.embed([this.queryPrefix + text]);
    if (vector === undefined) {
      throw new UpstreamError('ollama', 'no embedding returned for the query');
    }
    return vector;
  }

  async health(): Promise<void> {
    await requestJson(this.fetchFn, 'ollama', `${this.baseUrl}/api/version`, { method: 'GET', timeoutMs: 5_000 });
  }

  private async embed(input: string[]): Promise<number[][]> {
    const { body } = await requestJson<EmbedResponse>(this.fetchFn, 'ollama', `${this.baseUrl}/api/embed`, {
      method: 'POST',
      // truncate: inputs longer than the model context are cut instead of failing.
      body: { model: this.model, input, truncate: true },
      timeoutMs: this.timeoutMs,
    });
    const embeddings = body.embeddings;
    if (!Array.isArray(embeddings) || embeddings.length !== input.length) {
      throw new UpstreamError('ollama', `expected ${input.length} embeddings, received ${Array.isArray(embeddings) ? embeddings.length : 'none'}`);
    }
    return embeddings;
  }
}
