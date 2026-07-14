"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { UserCircle, RefreshCw, Zap, Brain, TrendingUp, AlertTriangle, Clock, Star } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

function SkillBar({ name, score }: { name: string; score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div className="flex items-center gap-3">
      <div className="w-24 text-[12px] text-muted truncate capitalize">{name}</div>
      <div className="flex-1 h-2 rounded-full bg-surface-2 overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
          className={`h-full rounded-full ${
            pct >= 70 ? "bg-green" : pct >= 40 ? "bg-accent" : "bg-amber"
          }`}
        />
      </div>
      <div className="w-8 text-right text-[11px] text-faint tabular-nums">{pct}%</div>
    </div>
  );
}

function HeatmapHour({ hour, count, max }: { hour: number; count: number; max: number }) {
  const intensity = max > 0 ? count / max : 0;
  const label = `${hour}:00`;
  return (
    <div className="flex flex-col items-center gap-1">
      <div
        style={{ opacity: 0.15 + intensity * 0.85 }}
        className={`w-6 h-6 rounded ${intensity > 0 ? "bg-accent" : "bg-surface-2"}`}
        title={`${label}: ${count} memories`}
      />
      {hour % 6 === 0 && (
        <span className="text-[9px] text-faint">{hour}h</span>
      )}
    </div>
  );
}

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function DigitalTwinPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();

  const { data: twin, isLoading } = useQuery({
    queryKey: ["digital-twin", workspace?.id],
    queryFn: () => api.getDigitalTwin(workspace!.id),
    enabled: !!workspace,
  });

  const { data: evolutionLog } = useQuery({
    queryKey: ["evolution-log", workspace?.id],
    queryFn: () => api.getEvolutionLog(workspace!.id),
    enabled: !!workspace,
  });

  const { data: reports } = useQuery({
    queryKey: ["eval-reports", workspace?.id],
    queryFn: () => api.listEvaluationReports(workspace!.id),
    enabled: !!workspace,
  });

  const refreshMut = useMutation({
    mutationFn: () => api.refreshDigitalTwin(workspace!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digital-twin"] }),
  });

  const evolutionMut = useMutation({
    mutationFn: () => api.runEvolution(workspace!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["evolution-log"] });
      qc.invalidateQueries({ queryKey: ["digital-twin"] });
    },
  });

  const evalMut = useMutation({
    mutationFn: () => api.runEvaluation(workspace!.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["eval-reports"] }),
  });

  const skills = Object.entries(twin?.skills ?? {})
    .sort(([, a], [, b]) => (b as number) - (a as number))
    .slice(0, 15);

  const hourlyData = twin?.productivity?.by_hour ?? {};
  const maxHour = Math.max(...Object.values(hourlyData).map(Number), 1);

  const dowData = twin?.productivity?.by_weekday ?? {};

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <UserCircle className="size-5 text-accent" /> Digital Twin
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Your continuously evolving AI profile built from {twin?.memory_count_at_last_update ?? "…"} memories.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => refreshMut.mutate()}
            disabled={refreshMut.isPending || !workspace}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-[12px] text-muted hover:text-text disabled:opacity-50"
          >
            <RefreshCw className={`size-3.5 ${refreshMut.isPending ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Skill graph */}
        <div className="lg:col-span-2 card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <Brain className="size-3.5 text-faint" /> Skill Graph
          </h2>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(8)].map((_, i) => <div key={i} className="skeleton h-4 rounded" />)}
            </div>
          ) : skills.length > 0 ? (
            <div className="space-y-3">
              {skills.map(([name, score]) => (
                <SkillBar key={name} name={name} score={score as number} />
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-faint">Add more memories to build your skill graph.</p>
          )}
        </div>

        {/* Style + tools */}
        <div className="space-y-4">
          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <Zap className="size-3.5 text-faint" /> Coding Style
            </h2>
            {twin?.style ? (
              <div className="space-y-1.5">
                {Object.entries(twin.style).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-[12px]">
                    <span className="text-faint capitalize">{k.replace(/_/g, " ")}</span>
                    <span className="font-medium">{typeof v === "number" ? `${Math.round((v as number) * 100)}%` : String(v)}</span>
                  </div>
                ))}
              </div>
            ) : <div className="skeleton h-20" />}
          </div>

          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <Star className="size-3.5 text-faint" /> Favourite Tools
            </h2>
            <div className="flex flex-wrap gap-1.5">
              {twin?.favorite_tools?.slice(0, 10).map((t: string) => (
                <span key={t} className="rounded-full bg-accent/10 text-accent px-2.5 py-0.5 text-[11px] font-medium">
                  {t}
                </span>
              )) ?? <div className="skeleton h-8 w-full rounded-lg" />}
            </div>
          </div>
        </div>

        {/* Productivity heatmap */}
        <div className="lg:col-span-2 card p-5">
          <h2 className="text-[13px] font-medium mb-4 flex items-center gap-2">
            <Clock className="size-3.5 text-faint" /> Productivity Heatmap
          </h2>
          <div className="flex gap-1 flex-wrap">
            {[...Array(24)].map((_, h) => (
              <HeatmapHour
                key={h}
                hour={h}
                count={Number(hourlyData[String(h)] ?? 0)}
                max={maxHour}
              />
            ))}
          </div>
          <div className="mt-4 flex gap-4">
            {DOW.map((day, i) => {
              const count = Number(dowData[String(i)] ?? 0);
              const max = Math.max(...Object.values(dowData).map(Number), 1);
              const pct = Math.round((count / max) * 100);
              return (
                <div key={day} className="flex-1 text-center">
                  <div className="h-12 flex items-end justify-center">
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${Math.max(pct, 4)}%` }}
                      className="w-4 rounded-t bg-accent/60"
                    />
                  </div>
                  <div className="text-[10px] text-faint mt-1">{day}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Predictions + Gaps */}
        <div className="space-y-4">
          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <TrendingUp className="size-3.5 text-faint" /> Predicted Interests
            </h2>
            {twin?.predictions?.length ? (
              <div className="space-y-1.5">
                {twin.predictions.map((p: string, i: number) => (
                  <div key={p} className="flex items-center gap-2 text-[12px]">
                    <span className="text-faint">#{i + 1}</span>
                    <span>{p}</span>
                  </div>
                ))}
              </div>
            ) : <p className="text-[12px] text-faint">Not enough data yet.</p>}
          </div>

          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <AlertTriangle className="size-3.5 text-amber" /> Knowledge Gaps
            </h2>
            <div className="flex flex-wrap gap-1.5">
              {twin?.gaps?.slice(0, 10).map((g: string) => (
                <span key={g} className="rounded-full bg-amber/10 text-amber px-2.5 py-0.5 text-[11px]">
                  {g}
                </span>
              )) ?? <div className="skeleton h-8 w-full rounded-lg" />}
            </div>
          </div>
        </div>

        {/* Knowledge Evolution */}
        <div className="lg:col-span-2 card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[13px] font-medium flex items-center gap-2">
              <Zap className="size-3.5 text-faint" /> Knowledge Evolution Log
            </h2>
            <button
              onClick={() => evolutionMut.mutate()}
              disabled={evolutionMut.isPending || !workspace}
              className="flex items-center gap-1.5 rounded-lg bg-accent/10 text-accent px-3 py-1.5 text-[12px] font-medium hover:bg-accent/20 disabled:opacity-50"
            >
              <RefreshCw className={`size-3 ${evolutionMut.isPending ? "animate-spin" : ""}`} />
              Run Evolution
            </button>
          </div>
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {evolutionLog?.slice(0, 20).map((entry: any) => (
              <div key={entry.id} className="flex items-center gap-3 text-[12px]">
                <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted w-28 text-center shrink-0">
                  {entry.action}
                </span>
                <span className="text-faint font-mono text-[10px] truncate">{entry.memory_id || "workspace"}</span>
                <span className="ml-auto text-faint text-[10px] shrink-0">
                  {new Date(entry.created_at).toLocaleTimeString()}
                </span>
              </div>
            ))}
            {!evolutionLog?.length && (
              <p className="text-[12px] text-faint">No evolution actions yet. Run evolution to start.</p>
            )}
          </div>
        </div>

        {/* AI Evaluation */}
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[13px] font-medium">AI Evaluation</h2>
            <button
              onClick={() => evalMut.mutate()}
              disabled={evalMut.isPending || !workspace}
              className="rounded-lg bg-accent/10 text-accent px-3 py-1.5 text-[12px] font-medium hover:bg-accent/20 disabled:opacity-50"
            >
              {evalMut.isPending ? "Running…" : "Run Now"}
            </button>
          </div>
          {reports?.[0] ? (
            <div className="space-y-2">
              <EvalRow label="Retrieval NDCG" value={reports[0].retrieval_quality} />
              <EvalRow label="Grounding" value={reports[0].grounding_accuracy} />
              <EvalRow label="Hallucination ↓" value={reports[0].hallucination_rate} invert />
              <EvalRow label="Citation" value={reports[0].citation_accuracy} />
              <EvalRow label="Agent Success" value={reports[0].agent_success_rate} />
              <div className="pt-1 text-[10px] text-faint">
                Avg latency: {reports[0].avg_latency_ms.toFixed(0)}ms
              </div>
            </div>
          ) : (
            <p className="text-[12px] text-faint">No evaluation reports. Run evaluation to start.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function EvalRow({ label, value, invert }: { label: string; value: number; invert?: boolean }) {
  const pct = Math.round(value * 100);
  const good = invert ? pct < 10 : pct > 70;
  const bad = invert ? pct > 30 : pct < 40;
  return (
    <div className="flex items-center gap-3">
      <div className="w-28 text-[12px] text-muted">{label}</div>
      <div className="flex-1 h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div
          style={{ width: `${pct}%` }}
          className={`h-full rounded-full ${good ? "bg-green" : bad ? "bg-red" : "bg-amber"}`}
        />
      </div>
      <div className={`text-[11px] font-medium tabular-nums ${good ? "text-green" : bad ? "text-red" : "text-amber"}`}>
        {pct}%
      </div>
    </div>
  );
}
