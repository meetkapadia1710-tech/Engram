export interface Workspace {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  memory_count: number;
}

export interface EntityRef {
  id: string;
  name: string;
  kind: string;
}

export interface Memory {
  id: string;
  workspace_id: string;
  type: string;
  title: string;
  content: string;
  summary: string;
  keywords: string[];
  tags: string[];
  source: string;
  author: string;
  importance: number;
  confidence: number;
  access_count: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
  entities: EntityRef[];
}

export interface SearchResult {
  memory: Memory;
  score: number;
  components: Record<string, number>;
}

export interface GraphNode {
  id: string;
  kind: "memory" | "entity";
  label: string;
  type: string;
  importance?: number;
  mentions?: number;
  degree: number;
  created_at?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Analytics {
  memories: number;
  archived: number;
  entities: number;
  relationships: number;
  by_type: Record<string, number>;
  activity: { date: string; count: number }[];
  top_entities: { name: string; kind: string; mentions: number }[];
}

export interface ContextResult {
  query: string;
  context: string;
  sources: { n: number; id: string; title: string; type: string; created_at: string; score: number }[];
  approx_tokens: number;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  embedding_provider: string;
  generation_provider: string;
  dependencies: {
    supermemory: {
      reachable: boolean;
      url: string;
      latency_ms: number;
      error: string | null;
    };
  };
}
