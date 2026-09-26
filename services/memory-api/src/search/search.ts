import type { Embedder, VectorStore } from '../ports.js';

export interface SearchQuery {
  query: string;
  limit: number;
  tags?: string[];
  minScore?: number;
}

/** One relevant chunk and the note it comes from, ready to be cited. */
export interface SearchResult {
  score: number;
  path: string;
  title: string;
  section: string;
  tags: string[];
  chunkIndex: number;
  text: string;
}

export class SearchService {
  constructor(
    private readonly embedder: Embedder,
    private readonly store: VectorStore,
  ) {}

  async search(query: SearchQuery): Promise<SearchResult[]> {
    const vector = await this.embedder.embedQuery(query.query);
    const hits = await this.store.search(vector, {
      limit: query.limit,
      ...(query.tags === undefined ? {} : { tags: query.tags.map((tag) => tag.replace(/^#/, '').toLowerCase()) }),
      ...(query.minScore === undefined ? {} : { minScore: query.minScore }),
    });
    return hits.map(({ score, payload }) => ({
      score,
      path: payload.path,
      title: payload.title,
      section: payload.section,
      tags: payload.tags,
      chunkIndex: payload.chunk_index,
      text: payload.text,
    }));
  }
}
