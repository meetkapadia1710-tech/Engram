"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Workflow, Plus, Play, Trash2, CheckCircle, XCircle,
  AlertCircle, Clock, ChevronRight, Zap, Code2
} from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const STEP_TYPES = ["search", "context", "summarize", "create_memory", "tool", "condition", "for_each"];

const STATUS_STYLE: Record<string, string> = {
  ok: "text-green",
  failed: "text-red",
  running: "text-accent",
  skipped: "text-amber",
};

const EXAMPLE_WORKFLOW = {
  name: "Daily Knowledge Digest",
  description: "Search today's memories, summarize, and store as a digest note.",
  trigger_event: "",
  enabled: true,
  steps: [
    { type: "search", query: "today", limit: 20, out: "recent" },
    { type: "summarize", text: "{recent}", out: "digest" },
    { type: "create_memory", content: "Daily digest: {digest}", memory_type: "note", tags: ["digest"] },
  ],
};

export default function WorkflowsPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", steps: "[]", trigger_event: "" });

  const { data: workflows } = useQuery({
    queryKey: ["workflows", workspace?.id],
    queryFn: () => api.listWorkflows(workspace!.id),
    enabled: !!workspace,
  });

  const { data: runs } = useQuery({
    queryKey: ["workflow-runs", workspace?.id],
    queryFn: () => api.listWorkflowRuns(workspace!.id),
    enabled: !!workspace,
    refetchInterval: 8000,
  });

  const { data: eventTypes } = useQuery({
    queryKey: ["event-types"],
    queryFn: () => api.listEventTypes(),
  });

  const createMut = useMutation({
    mutationFn: () => {
      const steps = JSON.parse(form.steps);
      return api.createWorkflow(workspace!.id, {
        name: form.name,
        description: form.description,
        trigger_event: form.trigger_event,
        steps,
        enabled: true,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflows"] });
      setShowCreate(false);
      setForm({ name: "", description: "", steps: "[]", trigger_event: "" });
    },
  });

  const triggerMut = useMutation({
    mutationFn: (id: string) => api.triggerWorkflow(workspace!.id, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workflow-runs"] }),
  });

  const loadExample = () => {
    setForm({
      name: EXAMPLE_WORKFLOW.name,
      description: EXAMPLE_WORKFLOW.description,
      steps: JSON.stringify(EXAMPLE_WORKFLOW.steps, null, 2),
      trigger_event: "",
    });
  };

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Workflow className="size-5 text-accent" /> Workflow Engine
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            Automate AI pipelines with search, summarize, memory, tools, and conditionals.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-2 rounded-lg bg-accent/90 px-4 py-2 text-[13px] font-medium text-white hover:bg-accent"
        >
          <Plus className="size-4" /> New workflow
        </button>
      </header>

      {/* Create form */}
      {showCreate && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-6 mb-6"
        >
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-medium">Create Workflow</h2>
            <button
              onClick={loadExample}
              className="flex items-center gap-1.5 text-[12px] text-accent hover:underline"
            >
              <Code2 className="size-3.5" /> Load example
            </button>
          </div>
          <div className="grid gap-3">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Workflow name"
              className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none focus:border-accent/60"
            />
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Description (optional)"
              className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none focus:border-accent/60"
            />
            <select
              value={form.trigger_event}
              onChange={(e) => setForm({ ...form, trigger_event: e.target.value })}
              className="rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none focus:border-accent/60"
            >
              <option value="">Manual trigger only</option>
              {eventTypes?.map((t: string) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <div>
              <div className="text-[11px] font-medium text-faint mb-1.5">
                Steps (JSON array) — types: {STEP_TYPES.join(", ")}
              </div>
              <textarea
                value={form.steps}
                onChange={(e) => setForm({ ...form, steps: e.target.value })}
                rows={8}
                className="w-full rounded-lg border border-border bg-surface-2 p-3 text-[12px] font-mono outline-none focus:border-accent/60 resize-none"
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => createMut.mutate()}
                disabled={!form.name || createMut.isPending}
                className="flex-1 rounded-lg bg-accent/90 py-2 text-[13px] font-medium text-white hover:bg-accent disabled:opacity-50"
              >
                {createMut.isPending ? "Creating…" : "Create workflow"}
              </button>
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-lg border border-border px-4 py-2 text-[13px] text-muted hover:text-text"
              >
                Cancel
              </button>
            </div>
            {createMut.isError && (
              <p className="text-[12px] text-red">{(createMut.error as Error).message}</p>
            )}
          </div>
        </motion.div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Workflow list */}
        <div className="lg:col-span-3 space-y-3">
          <h2 className="text-[13px] font-medium text-muted">Workflows</h2>
          {workflows?.map((wf: any, i: number) => (
            <motion.div
              key={wf.id}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: i * 0.04 }}
              className="card p-4 flex items-center gap-3"
            >
              <div className={`size-2 rounded-full ${wf.enabled ? "bg-green" : "bg-surface-2"}`} />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-medium">{wf.name}</div>
                <div className="text-[11px] text-faint mt-0.5 flex items-center gap-2">
                  {wf.trigger_event ? (
                    <span className="flex items-center gap-1"><Zap className="size-3" /> {wf.trigger_event}</span>
                  ) : (
                    <span>Manual</span>
                  )}
                  · {wf.steps.length} step{wf.steps.length !== 1 ? "s" : ""}
                </div>
              </div>
              <button
                onClick={() => triggerMut.mutate(wf.id)}
                disabled={!wf.enabled || triggerMut.isPending}
                className="flex items-center gap-1.5 rounded-lg bg-accent/90 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-accent disabled:opacity-40"
              >
                <Play className="size-3.5" /> Run
              </button>
            </motion.div>
          ))}
          {!workflows && [...Array(3)].map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)}
          {workflows?.length === 0 && (
            <div className="card grid place-items-center p-10 text-center">
              <Workflow className="size-10 text-faint mb-3" />
              <p className="text-[13px] text-muted">No workflows yet. Create one above.</p>
            </div>
          )}
        </div>

        {/* Run history */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-[13px] font-medium text-muted">Recent Runs</h2>
          {runs?.slice(0, 15).map((run: any) => (
            <div key={run.id} className="card p-3 flex items-center gap-3">
              {run.status === "ok" && <CheckCircle className="size-4 text-green shrink-0" />}
              {run.status === "failed" && <XCircle className="size-4 text-red shrink-0" />}
              {run.status === "running" && <Clock className="size-4 text-accent animate-pulse shrink-0" />}
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-medium truncate">{run.trigger}</div>
                <div className="text-[11px] text-faint">{new Date(run.started_at).toLocaleString()}</div>
              </div>
              <span className={`text-[11px] font-medium ${STATUS_STYLE[run.status]}`}>
                {run.status}
              </span>
            </div>
          ))}
          {!runs && [...Array(5)].map((_, i) => <div key={i} className="skeleton h-12 rounded-xl" />)}
        </div>
      </div>
    </div>
  );
}
