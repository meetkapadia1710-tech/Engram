/**
 * Engram TypeScript SDK — give any agent long-term memory.
 *
 * ```ts
 * import { Engram } from "@engram/sdk";
 * const em = new Engram({ baseUrl: "http://localhost:8000" });
 * await em.createMemory({ content: "Docker layers are cached." });
 * const hits = await em.search({ query: "docker" });
 * ```
 */

export interface EngramOptions {
  baseUrl?: string;
  apiKey?: string;
  workspace?: string;
}

export interface MemoryRecord {
  id: string;
  title: string;
  content: string;
  type: string;
  summary: string;
  keywords: string[];
  tags: string[];
  importance: number;
  created_at: string;
  entities: { id: string; name: string; kind: string }[];
}

export interface SearchHit {
  memory: MemoryRecord;
  score: number;
  components: Record<string, number>;
}

export interface ContextResult {
  query: string;
  context: string;
  sources: { n: number; id: string; title: string; type: string; score: number }[];
  approx_tokens: number;
}

export class EngramError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`[${status}] ${detail}`);
  }
}

export class Engram {
  private baseUrl: string;
  private apiKey: string;
  private workspaceId: string;

  constructor(opts: EngramOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.apiKey = opts.apiKey ?? "";
    this.workspaceId = opts.workspace ?? "";
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(this.apiKey ? { "X-API-Key": this.apiKey } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 204) return undefined as T;
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* keep statusText */
      }
      throw new EngramError(res.status, String(detail));
    }
    return res.json() as Promise<T>;
  }

  private async workspace(): Promise<string> {
    if (this.workspaceId) return this.workspaceId;
    const { items } = await this.request<{ items: { id: string }[] }>(
      "GET",
      "/v1/workspaces",
    );
    if (items.length > 0) {
      this.workspaceId = items[0].id;
    } else {
      const created = await this.request<{ id: string }>("POST", "/v1/workspaces", {
        name: "Personal",
      });
      this.workspaceId = created.id;
    }
    return this.workspaceId;
  }

  async createMemory(input: {
    content: string;
    type?: string;
    title?: string;
    tags?: string[];
    source?: string;
  }): Promise<MemoryRecord> {
    const ws = await this.workspace();
    return this.request("POST", `/v1/workspaces/${ws}/memories`, {
      type: "note",
      ...input,
    });
  }

  async getMemory(id: string): Promise<MemoryRecord> {
    return this.request("GET", `/v1/memories/${id}`);
  }

  async updateMemory(
    id: string,
    fields: Partial<Pick<MemoryRecord, "title" | "content" | "tags" | "importance">> & {
      archived?: boolean;
    },
  ): Promise<MemoryRecord> {
    return this.request("PATCH", `/v1/memories/${id}`, fields);
  }

  async deleteMemory(id: string): Promise<void> {
    await this.request("DELETE", `/v1/memories/${id}`);
  }

  async search(input: {
    query: string;
    limit?: number;
    mode?: "hybrid" | "vector" | "keyword";
    types?: string[];
    date_from?: string;
    date_to?: string;
  }): Promise<SearchHit[]> {
    const ws = await this.workspace();
    const { results } = await this.request<{ results: SearchHit[] }>(
      "POST",
      `/v1/workspaces/${ws}/search`,
      input,
    );
    return results;
  }

  async retrieveContext(query: string, maxTokens = 1800): Promise<ContextResult> {
    const ws = await this.workspace();
    return this.request("POST", `/v1/workspaces/${ws}/context`, {
      query,
      max_tokens: maxTokens,
    });
  }

  async findRelated(memoryId: string, limit = 8) {
    const { items } = await this.request<{ items: unknown[] }>(
      "GET",
      `/v1/memories/${memoryId}/related?limit=${limit}`,
    );
    return items;
  }

  async knowledgeGraph(center?: string) {
    const ws = await this.workspace();
    const q = center ? `?center=${encodeURIComponent(center)}` : "";
    return this.request("GET", `/v1/workspaces/${ws}/graph${q}`);
  }

  async analytics() {
    const ws = await this.workspace();
    return this.request("GET", `/v1/workspaces/${ws}/analytics`);
  }
}
