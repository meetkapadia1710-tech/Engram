import type {
  Analytics,
  ContextResult,
  GraphData,
  Memory,
  SearchResult,
  Workspace,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),

  listWorkspaces: () =>
    request<{ items: Workspace[] }>("/v1/workspaces").then((r) => r.items),
  createWorkspace: (name: string) =>
    request<Workspace>("/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  listMemories: (ws: string, opts?: { limit?: number; type?: string }) => {
    const p = new URLSearchParams();
    if (opts?.limit) p.set("limit", String(opts.limit));
    if (opts?.type) p.set("type", opts.type);
    return request<{ items: Memory[] }>(
      `/v1/workspaces/${ws}/memories?${p.toString()}`,
    ).then((r) => r.items);
  },
  createMemory: (
    ws: string,
    body: { content: string; type?: string; title?: string; tags?: string[]; source?: string },
  ) =>
    request<Memory>(`/v1/workspaces/${ws}/memories`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteMemory: (id: string) =>
    request<void>(`/v1/memories/${id}`, { method: "DELETE" }),
  relatedMemories: (id: string) =>
    request<{ items: { id: string; title: string; kind: string; weight: number; summary: string }[] }>(
      `/v1/memories/${id}/related`,
    ).then((r) => r.items),

  search: (
    ws: string,
    body: { query: string; mode?: string; limit?: number; types?: string[]; date_from?: string },
  ) =>
    request<{ results: SearchResult[] }>(`/v1/workspaces/${ws}/search`, {
      method: "POST",
      body: JSON.stringify(body),
    }).then((r) => r.results),

  context: (ws: string, query: string, maxTokens = 1800) =>
    request<ContextResult>(`/v1/workspaces/${ws}/context`, {
      method: "POST",
      body: JSON.stringify({ query, max_tokens: maxTokens }),
    }),

  graph: (ws: string, center?: string) => {
    const p = new URLSearchParams();
    if (center) p.set("center", center);
    return request<GraphData>(`/v1/workspaces/${ws}/graph?${p.toString()}`);
  },

  analytics: (ws: string) => request<Analytics>(`/v1/workspaces/${ws}/analytics`),

  memoryTypes: () => request<string[]>("/v1/types"),
};
