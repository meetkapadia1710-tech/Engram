"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Brain, GitBranch, Layers, Archive } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";
import { MemoryCard } from "@/components/MemoryCard";

function Stat({
  label,
  value,
  icon: Icon,
  tint,
}: {
  label: string;
  value: number | string;
  icon: React.ElementType;
  tint: string;
}) {
  return (
    <div className="card flex items-center gap-4 p-5">
      <span className={`grid size-10 place-items-center rounded-xl ${tint}`}>
        <Icon className="size-5" />
      </span>
      <div>
        <div className="text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
        <div className="text-[12px] text-muted">{label}</div>
      </div>
    </div>
  );
}

function ActivityChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div className="flex h-24 items-end gap-1.5">
      {data.map((d, i) => (
        <motion.div
          key={d.date}
          initial={{ height: 0 }}
          animate={{ height: `${Math.max((d.count / max) * 100, 4)}%` }}
          transition={{ duration: 0.4, delay: i * 0.03 }}
          title={`${d.date}: ${d.count}`}
          className={`flex-1 rounded-t ${d.count > 0 ? "bg-accent/70" : "bg-surface-2"}`}
        />
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { workspace, loading, error } = useWorkspace();

  const { data: analytics } = useQuery({
    queryKey: ["analytics", workspace?.id],
    queryFn: () => api.analytics(workspace!.id),
    enabled: !!workspace,
  });

  const { data: recent } = useQuery({
    queryKey: ["recent", workspace?.id],
    queryFn: () => api.listMemories(workspace!.id, { limit: 6 }),
    enabled: !!workspace,
  });

  if (error) {
    return (
      <div className="card mx-auto mt-24 max-w-md p-8 text-center">
        <h2 className="mb-2 text-lg font-semibold">Can&apos;t reach the Engram API</h2>
        <p className="text-[13px] text-muted">
          Start it with{" "}
          <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[12px]">
            python -m uvicorn app.main:app --port 8000
          </code>{" "}
          in <span className="font-mono">services/api</span>, then reload.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8">
        <h1 className="text-xl font-semibold tracking-tight">
          {loading ? "Connecting…" : "Everything you've ever told your AI"}
        </h1>
        <p className="mt-1 text-[13px] text-muted">
          Hybrid search, knowledge graph, and temporal recall over {analytics?.memories ?? "…"}{" "}
          memories.
        </p>
      </header>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Memories" value={analytics?.memories ?? "—"} icon={Brain} tint="bg-accent-soft text-accent" />
        <Stat label="Entities" value={analytics?.entities ?? "—"} icon={Layers} tint="bg-cyan/10 text-cyan" />
        <Stat label="Relationships" value={analytics?.relationships ?? "—"} icon={GitBranch} tint="bg-green/10 text-green" />
        <Stat label="Archived" value={analytics?.archived ?? "—"} icon={Archive} tint="bg-amber/10 text-amber" />
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <div className="card p-5 lg:col-span-2">
          <h2 className="mb-4 text-[13px] font-medium text-muted">Activity · last 14 days</h2>
          {analytics ? (
            <ActivityChart data={analytics.activity} />
          ) : (
            <div className="skeleton h-24" />
          )}
        </div>
        <div className="card p-5">
          <h2 className="mb-3 text-[13px] font-medium text-muted">Top entities</h2>
          <div className="flex flex-col gap-2">
            {analytics?.top_entities.slice(0, 6).map((e) => (
              <div key={e.name} className="flex items-center justify-between text-[12.5px]">
                <span className="truncate">{e.name}</span>
                <span className="ml-2 shrink-0 font-mono text-[11px] text-faint">
                  ×{e.mentions}
                </span>
              </div>
            )) ?? <div className="skeleton h-24" />}
            {analytics && analytics.top_entities.length === 0 && (
              <p className="text-[12px] text-faint">No entities yet.</p>
            )}
          </div>
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-[13px] font-medium text-muted">Recent memories</h2>
        {recent === undefined ? (
          <div className="grid gap-3 md:grid-cols-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="skeleton h-28" />
            ))}
          </div>
        ) : recent.length === 0 ? (
          <div className="card grid place-items-center p-12 text-center">
            <p className="text-[13px] text-muted">
              No memories yet. Press <kbd className="rounded border border-border px-1.5 py-0.5 font-mono text-[11px]">⌘K</kbd>{" "}
              or hit <span className="text-accent">New memory</span> to teach Engram something.
            </p>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {recent.map((m, i) => (
              <MemoryCard key={m.id} memory={m} index={i} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
