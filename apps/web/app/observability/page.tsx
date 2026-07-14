"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Activity, TrendingUp, Zap, Clock, Cpu, AlertCircle, CheckCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

function MetricCard({ label, value, sub, tint }: { label: string; value: string | number; sub?: string; tint?: string }) {
  return (
    <div className="card p-5">
      <div className={`text-2xl font-semibold tabular-nums tracking-tight ${tint ?? "text-text"}`}>
        {value}
      </div>
      <div className="text-[12px] font-medium mt-1">{label}</div>
      {sub && <div className="text-[11px] text-faint mt-0.5">{sub}</div>}
    </div>
  );
}

function LatencyBar({ name, data }: { name: string; data: any }) {
  if (!data) return null;
  const avg = data.avg_ms ?? 0;
  const p95 = data.p95_ms ?? 0;
  const maxMs = 500;
  return (
    <div className="flex items-center gap-3">
      <div className="w-28 text-[12px] text-muted truncate">{name}</div>
      <div className="flex-1 h-2 rounded-full bg-surface-2 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.min((avg / maxMs) * 100, 100)}%` }}
          className="h-full rounded-full bg-accent/70"
        />
      </div>
      <div className="w-20 text-right text-[11px] text-faint tabular-nums">
        avg {avg.toFixed(0)}ms
      </div>
      <div className="w-20 text-right text-[11px] text-faint tabular-nums">
        p95 {p95.toFixed(0)}ms
      </div>
    </div>
  );
}

function CounterRow({ name, value }: { name: string; value: number }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
      <span className="text-[12px] font-mono text-muted">{name}</span>
      <span className="text-[12px] font-semibold tabular-nums">{value.toLocaleString()}</span>
    </div>
  );
}

export default function ObservabilityPage() {
  const { workspace } = useWorkspace();

  const { data: metrics, dataUpdatedAt } = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api.getMetrics(),
    refetchInterval: 10_000,
  });

  const { data: workers } = useQuery({
    queryKey: ["workers"],
    queryFn: () => api.getWorkerHealth(),
    refetchInterval: 10_000,
  });

  const { data: timelines } = useQuery({
    queryKey: ["timelines"],
    queryFn: () => api.getAgentTimelines(),
    refetchInterval: 10_000,
  });

  const uptime = metrics?.uptime_s
    ? `${Math.floor(metrics.uptime_s / 3600)}h ${Math.floor((metrics.uptime_s % 3600) / 60)}m`
    : "—";

  const totalEvents = Object.entries(metrics?.counters ?? {})
    .filter(([k]) => k.startsWith("events."))
    .reduce((s, [, v]) => s + (v as number), 0);

  const latencies = metrics?.latency ?? {};

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Activity className="size-5 text-accent" /> Observability
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Real-time platform metrics, latency histograms, and worker health.
            {dataUpdatedAt ? ` Last updated ${new Date(dataUpdatedAt).toLocaleTimeString()}` : ""}
          </p>
        </div>
      </header>

      {/* Top metrics */}
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Uptime" value={uptime} tint="text-green" />
        <MetricCard label="Total Events" value={totalEvents.toLocaleString()} tint="text-accent" />
        <MetricCard
          label="Workflow Runs"
          value={(workers?.workflows?.ok ?? 0) + (workers?.workflows?.failed ?? 0)}
          sub={`${workers?.workflows?.failed ?? 0} failed`}
        />
        <MetricCard
          label="Agent Runs"
          value={workers?.agents?.total_runs ?? "—"}
          sub={`${workers?.agents?.running ?? 0} running`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Latency heatmap */}
        <div className="card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <Clock className="size-3.5 text-faint" /> Latency (avg / p95)
          </h2>
          <div className="space-y-3">
            {Object.entries(latencies).map(([name, data]) => (
              <LatencyBar key={name} name={name} data={data} />
            ))}
            {Object.keys(latencies).length === 0 && (
              <p className="text-[12px] text-faint">No requests recorded yet.</p>
            )}
          </div>
        </div>

        {/* Event counters */}
        <div className="card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <Zap className="size-3.5 text-faint" /> Event Counters
          </h2>
          <div>
            {Object.entries(metrics?.counters ?? {})
              .filter(([k]) => k.startsWith("events."))
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .map(([name, value]) => (
                <CounterRow key={name} name={name} value={value as number} />
              ))}
            {Object.keys(metrics?.counters ?? {}).length === 0 && (
              <p className="text-[12px] text-faint">No counters yet.</p>
            )}
          </div>
        </div>

        {/* Worker health */}
        <div className="card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <Cpu className="size-3.5 text-faint" /> Worker Health
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-[11px] font-semibold text-faint mb-2">Workflows</div>
              <div className="space-y-1">
                <Row label="Running" value={workers?.workflows?.running ?? 0} />
                <Row label="Succeeded" value={workers?.workflows?.ok ?? 0} good />
                <Row label="Failed" value={workers?.workflows?.failed ?? 0} bad />
                <Row label="Avg latency" value={`${(workers?.workflows?.avg_latency_ms ?? 0).toFixed(0)}ms`} />
              </div>
            </div>
            <div>
              <div className="text-[11px] font-semibold text-faint mb-2">Agents</div>
              <div className="space-y-1">
                <Row label="Running" value={workers?.agents?.running ?? 0} />
                <Row label="Total runs" value={workers?.agents?.total_runs ?? 0} />
                <Row label="Avg latency" value={`${(workers?.agents?.avg_latency_ms ?? 0).toFixed(0)}ms`} />
              </div>
            </div>
          </div>
        </div>

        {/* Agent timelines */}
        <div className="card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <TrendingUp className="size-3.5 text-faint" /> Agent Timelines
          </h2>
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {timelines?.agent_runs?.slice(0, 20).map((run: any) => (
              <div key={run.id} className="flex items-center gap-3 text-[12px]">
                {run.status === "ok" ? (
                  <CheckCircle className="size-3.5 text-green shrink-0" />
                ) : run.status === "running" ? (
                  <Activity className="size-3.5 text-accent shrink-0" />
                ) : (
                  <AlertCircle className="size-3.5 text-red shrink-0" />
                )}
                <span className="text-faint text-[11px] w-32 shrink-0">
                  {run.started_at ? new Date(run.started_at).toLocaleTimeString() : "—"}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-surface-2">
                  {run.duration_ms && (
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(run.duration_ms / 30000 * 100, 100)}%` }}
                      className="h-full rounded-full bg-accent/60"
                    />
                  )}
                </div>
                <span className="text-faint text-[11px] w-16 text-right tabular-nums">
                  {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "…"}
                </span>
              </div>
            ))}
            {!timelines?.agent_runs?.length && (
              <p className="text-[12px] text-faint">No agent runs recorded yet.</p>
            )}
          </div>
        </div>
      </div>

      {/* Tool counters */}
      {workers?.tools && Object.keys(workers.tools).length > 0 && (
        <div className="card p-5 mt-6">
          <h2 className="text-[13px] font-medium mb-4">Tool Usage</h2>
          <div className="grid gap-2 md:grid-cols-3">
            {Object.entries(workers.tools).map(([key, value]) => (
              <CounterRow key={key} name={key} value={value as number} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, good, bad }: { label: string; value: string | number; good?: boolean; bad?: boolean }) {
  return (
    <div className="flex justify-between text-[12px]">
      <span className="text-faint">{label}</span>
      <span className={good ? "text-green font-medium" : bad && (value as number) > 0 ? "text-red font-medium" : "font-medium tabular-nums"}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </span>
    </div>
  );
}
