"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/types";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 15_000 } },
});

// ---------------------------------------------------------------------------
// Workspace context: auto-provisions a "Personal" workspace on first launch.
// ---------------------------------------------------------------------------

interface WorkspaceCtx {
  workspace: Workspace | null;
  loading: boolean;
  error: string | null;
}

const WsContext = createContext<WorkspaceCtx>({
  workspace: null,
  loading: true,
  error: null,
});

export function useWorkspace() {
  return useContext(WsContext);
}

function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [provisioned, setProvisioned] = useState<Workspace | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const list = await api.listWorkspaces();
      if (list.length > 0) return list[0];
      const created = await api.createWorkspace("Personal");
      setProvisioned(created);
      return { ...created, memory_count: 0 };
    },
  });

  const value = useMemo(
    () => ({
      workspace: data ?? provisioned,
      loading: isLoading,
      error: error ? String(error) : null,
    }),
    [data, provisioned, isLoading, error],
  );

  return <WsContext.Provider value={value}>{children}</WsContext.Provider>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <WorkspaceProvider>{children}</WorkspaceProvider>
    </QueryClientProvider>
  );
}
