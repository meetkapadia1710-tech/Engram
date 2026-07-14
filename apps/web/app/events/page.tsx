"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Radio, RefreshCw, AlertTriangle, ChevronDown, ChevronRight, Filter } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const EVENT_COLORS: Record<string, string> = {
  MemoryCreated: "bg-green/10 text-green",
  MemoryUpdated: "bg-cyan/10 text-cyan",
  MemoryDeleted: "bg-red/10 text-red",
  EmbeddingGenerated: "bg-accent/10 text-accent",
  GraphUpdated: "bg-purple/10 text-purple",
  WorkspaceCreated: "bg-amber/10 text-amber",
  ContextBuilt: "bg-pink/10 text-pink",
  SearchExecuted: "bg-indigo/10 text-indigo",
};

export default function EventsPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const [filterType, setFilterType] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: events, isRefetching, refetch } = useQuery({
    queryKey: ["events", workspace?.id, filterType],
    queryFn: () => api.listEvents(workspace!.id, { type: filterType || undefined, limit: 100 }),
    enabled: !!workspace,
    refetchInterval: 5000,
  });

  const { data: dlq } = useQuery({
    queryKey: ["dlq"],
    queryFn: () => api.getDlq(),
    refetchInterval: 15_000,
  });

  const { data: eventTypes } = useQuery({
    queryKey: ["event-types"],
    queryFn: () => api.listEventTypes(),
  });

  const replayMut = useMutation({
    mutationFn: (id: string) => api.replayEvent(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["dlq"] });
    },
  });

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Radio className="size-5 text-accent" /> Event Bus
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Real-time event stream, subscriber management, and dead-letter queue.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isRefetching}
          className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[12px] text-muted hover:text-text disabled:opacity-50"
        >
          <RefreshCw className={`size-3.5 ${isRefetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </header>

      <div className="grid gap-6 lg:grid-cols-4">
        {/* Main event feed */}
        <div className="lg:col-span-3 space-y-4">
          {/* Filter */}
          <div className="flex items-center gap-3">
            <Filter className="size-3.5 text-faint shrink-0" />
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => setFilterType("")}
                className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${!filterType ? "bg-accent text-white" : "bg-surface-2 text-muted hover:text-text"}`}
              >
                All
              </button>
              {eventTypes?.slice(0, 10).map((t: string) => (
                <button
                  key={t}
                  onClick={() => setFilterType(filterType === t ? "" : t)}
                  className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${filterType === t ? "bg-accent text-white" : "bg-surface-2 text-muted hover:text-text"}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Events list */}
          <div className="space-y-2">
            {events?.map((event: any) => (
              <motion.div
                key={event.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="card overflow-hidden"
              >
                <button
                  onClick={() => setExpandedId(expandedId === event.id ? null : event.id)}
                  className="w-full flex items-center gap-3 p-3.5 text-left hover:bg-surface-2/40 transition"
                >
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0 ${EVENT_COLORS[event.type] ?? "bg-surface-2 text-muted"}`}>
                    {event.type}
                  </span>
                  <span className="text-[11px] text-faint font-mono truncate flex-1">
                    seq:{event.seq} · {event.id}
                  </span>
                  <span className="text-[10px] text-faint shrink-0">
                    {new Date(event.created_at).toLocaleTimeString()}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      replayMut.mutate(event.id);
                    }}
                    disabled={replayMut.isPending}
                    className="rounded px-2 py-1 text-[10px] text-muted hover:bg-surface-2 hover:text-text transition"
                  >
                    Replay
                  </button>
                  {expandedId === event.id ? (
                    <ChevronDown className="size-3.5 text-faint shrink-0" />
                  ) : (
                    <ChevronRight className="size-3.5 text-faint shrink-0" />
                  )}
                </button>

                <AnimatePresence>
                  {expandedId === event.id && (
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: "auto" }}
                      exit={{ height: 0 }}
                      className="border-t border-border overflow-hidden"
                    >
                      <pre className="p-4 text-[11px] font-mono text-muted whitespace-pre-wrap bg-surface-2/40 overflow-x-auto">
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            ))}
            {events?.length === 0 && (
              <div className="card grid place-items-center p-12 text-center">
                <Radio className="size-10 text-faint mb-3" />
                <p className="text-[13px] text-muted">No events yet. Create or search memories to generate events.</p>
              </div>
            )}
            {!events && [...Array(6)].map((_, i) => <div key={i} className="skeleton h-12 rounded-xl" />)}
          </div>
        </div>

        {/* DLQ sidebar */}
        <div className="space-y-4">
          <div className="card p-4">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <AlertTriangle className="size-3.5 text-amber" />
              Dead-Letter Queue
            </h2>
            {dlq?.length === 0 && (
              <p className="text-[12px] text-faint">No failed deliveries. ✓</p>
            )}
            {dlq?.map((entry: any) => (
              <div key={entry.id} className="mb-3 rounded-lg bg-red/5 border border-red/20 p-3">
                <div className="text-[11px] font-mono text-red truncate">{entry.event_id}</div>
                <div className="text-[11px] text-faint mt-1">{entry.subscriber}</div>
                <div className="text-[11px] text-faint">{entry.attempts} attempts</div>
                <div className="text-[10px] text-red/80 mt-1 truncate">{entry.last_error}</div>
                <button
                  onClick={() => replayMut.mutate(entry.event_id)}
                  className="mt-2 w-full rounded py-1.5 text-[11px] text-amber border border-amber/30 hover:bg-amber/10 transition"
                >
                  Retry
                </button>
              </div>
            ))}
          </div>

          {/* Event types */}
          <div className="card p-4">
            <h2 className="text-[13px] font-medium mb-3">Event Types</h2>
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {eventTypes?.map((t: string) => {
                const count = events?.filter((e: any) => e.type === t).length ?? 0;
                return (
                  <div key={t} className="flex items-center justify-between text-[12px]">
                    <button
                      onClick={() => setFilterType(filterType === t ? "" : t)}
                      className={`text-left hover:text-accent transition ${filterType === t ? "text-accent font-medium" : "text-muted"}`}
                    >
                      {t}
                    </button>
                    {count > 0 && (
                      <span className="text-[10px] text-faint">{count}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
