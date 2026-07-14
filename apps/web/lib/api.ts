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

  // ── Workspaces ────────────────────────────────────────────────────────────
  listWorkspaces: () =>
    request<{ items: Workspace[] }>("/v1/workspaces").then((r) => r.items),
  createWorkspace: (name: string) =>
    request<Workspace>("/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  // ── Memories ──────────────────────────────────────────────────────────────
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

  // ── Search ────────────────────────────────────────────────────────────────
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

  // ── Marketplace ──────────────────────────────────────────────────────────
  listCatalog: (opts?: { kind?: string; q?: string; first_party?: boolean }) => {
    const p = new URLSearchParams();
    if (opts?.kind) p.set("kind", opts.kind);
    if (opts?.q) p.set("q", opts.q);
    if (opts?.first_party !== undefined) p.set("first_party", String(opts.first_party));
    return request<{ total: number; items: any[] }>(`/v1/catalog?${p.toString()}`);
  },
  getCatalogEntry: (slug: string) => request<any>(`/v1/catalog/${slug}`),
  listInstalled: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/plugins`).then((r) => r.items),
  installPlugin: (ws: string, slug: string, version?: string) =>
    request<any>(`/v1/workspaces/${ws}/plugins/${slug}/install`, {
      method: "POST",
      body: JSON.stringify({ version: version ?? "" }),
    }),
  uninstallPlugin: (ws: string, slug: string) =>
    request<void>(`/v1/workspaces/${ws}/plugins/${slug}`, { method: "DELETE" }),
  updatePlugin: (ws: string, slug: string) =>
    request<any>(`/v1/workspaces/${ws}/plugins/${slug}/update`, { method: "POST" }),
  enablePlugin: (ws: string, slug: string) =>
    request<any>(`/v1/workspaces/${ws}/plugins/${slug}/enable`, { method: "POST" }),
  disablePlugin: (ws: string, slug: string) =>
    request<any>(`/v1/workspaces/${ws}/plugins/${slug}/disable`, { method: "POST" }),

  // ── Agents ────────────────────────────────────────────────────────────────
  listAgentTeam: () => request<{ agents: any[] }>("/v1/agents/team"),
  startAgentRun: (ws: string, goal: string, team?: string[]) =>
    request<any>(`/v1/workspaces/${ws}/agents/run`, {
      method: "POST",
      body: JSON.stringify({ goal, team }),
    }),
  listAgentRuns: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/agents/runs`).then((r) => r.items),
  getAgentRun: (ws: string, runId: string) =>
    request<any>(`/v1/workspaces/${ws}/agents/runs/${runId}`),

  // ── Workflows ─────────────────────────────────────────────────────────────
  listWorkflows: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/workflows`).then((r) => r.items),
  createWorkflow: (ws: string, body: any) =>
    request<any>(`/v1/workspaces/${ws}/workflows`, { method: "POST", body: JSON.stringify(body) }),
  triggerWorkflow: (ws: string, id: string, variables?: Record<string, unknown>) =>
    request<any>(`/v1/workspaces/${ws}/workflows/${id}/trigger`, {
      method: "POST",
      body: JSON.stringify({ variables: variables ?? {} }),
    }),
  listWorkflowRuns: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/workflow-runs`).then((r) => r.items),

  // ── Tools ─────────────────────────────────────────────────────────────────
  listTools: () => request<{ tools: any[] }>("/v1/tools").then((r) => r.tools),
  executeTool: (ws: string, name: string, args: Record<string, unknown>) =>
    request<any>(`/v1/workspaces/${ws}/tools/${name}`, {
      method: "POST",
      body: JSON.stringify({ args }),
    }),
  listToolExecutions: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/tool-executions`).then((r) => r.items),

  // ── Events ────────────────────────────────────────────────────────────────
  listEvents: (ws: string, opts?: { type?: string; limit?: number }) => {
    const p = new URLSearchParams();
    if (opts?.type) p.set("type", opts.type);
    if (opts?.limit) p.set("limit", String(opts.limit));
    return request<{ items: any[] }>(`/v1/workspaces/${ws}/events?${p.toString()}`).then((r) => r.items);
  },
  getDlq: () => request<{ items: any[] }>("/v1/events/dlq").then((r) => r.items),
  replayEvent: (id: string) =>
    request<any>(`/v1/events/${id}/replay`, { method: "POST" }),
  listEventTypes: () => request<{ event_types: string[] }>("/v1/events/types").then((r) => r.event_types),

  // ── Observability ─────────────────────────────────────────────────────────
  getMetrics: () => request<any>("/v1/metrics"),
  getWorkerHealth: () => request<any>("/v1/metrics/workers"),
  getAgentTimelines: () => request<any>("/v1/metrics/agent-timelines"),

  // ── Intelligence: Digital Twin ────────────────────────────────────────────
  getDigitalTwin: (ws: string) => request<any>(`/v1/workspaces/${ws}/digital-twin`),
  refreshDigitalTwin: (ws: string) =>
    request<any>(`/v1/workspaces/${ws}/digital-twin/refresh`, { method: "POST" }),

  // ── Intelligence: Knowledge Evolution ─────────────────────────────────────
  getEvolutionLog: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/evolution/log`).then((r) => r.items),
  runEvolution: (ws: string) =>
    request<any>(`/v1/workspaces/${ws}/evolution/run`, { method: "POST" }),

  // ── Intelligence: Evaluation ──────────────────────────────────────────────
  listEvaluationReports: (ws: string) =>
    request<{ items: any[] }>(`/v1/workspaces/${ws}/evaluation/reports`).then((r) => r.items),
  runEvaluation: (ws: string) =>
    request<any>(`/v1/workspaces/${ws}/evaluation/run`, { method: "POST" }),
};
