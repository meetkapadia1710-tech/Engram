"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Wrench, Play, CheckCircle, XCircle, Clock, ChevronRight } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const STATUS_STYLE: Record<string, string> = {
  ok: "text-green",
  denied: "text-red",
  error: "text-amber",
  timeout: "text-orange",
};

export default function ToolsPage() {
  const { workspace } = useWorkspace();
  const [selectedTool, setSelectedTool] = useState<any>(null);
  const [argsJson, setArgsJson] = useState("{}");
  const [lastResult, setLastResult] = useState<any>(null);

  const { data: tools } = useQuery({
    queryKey: ["tools"],
    queryFn: () => api.listTools(),
  });

  const { data: history } = useQuery({
    queryKey: ["tool-history", workspace?.id],
    queryFn: () => api.listToolExecutions(workspace!.id),
    enabled: !!workspace,
    refetchInterval: 10_000,
  });

  const execMut = useMutation({
    mutationFn: () => {
      const args = JSON.parse(argsJson);
      return api.executeTool(workspace!.id, selectedTool.name, args);
    },
    onSuccess: (data) => setLastResult(data),
  });

  const permColor = (p: string) => {
    if (p.includes("write") || p.includes("execute")) return "bg-red/10 text-red";
    if (p.includes("read") || p.includes("search")) return "bg-green/10 text-green";
    return "bg-surface-2 text-muted";
  };

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8">
        <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <Wrench className="size-5 text-accent" /> Tool Registry
        </h1>
        <p className="mt-1 text-[13px] text-muted">
          {tools?.length ?? "…"} tools available. All executions are sandboxed and audited.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Tool list */}
        <div className="lg:col-span-2 space-y-2">
          {tools?.map((tool: any, i: number) => (
            <motion.button
              key={tool.name}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04 }}
              onClick={() => {
                setSelectedTool(tool);
                setArgsJson(JSON.stringify(
                  Object.fromEntries(
                    Object.entries(tool.parameters?.properties ?? {}).map(([k, v]: [string, any]) => [
                      k, v.default ?? (v.type === "string" ? "" : v.type === "integer" ? 0 : null)
                    ])
                  ), null, 2
                ));
                setLastResult(null);
              }}
              className={`w-full text-left card p-4 transition hover:border-accent/40 ${
                selectedTool?.name === tool.name ? "border-accent/60" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="text-[13px] font-medium font-mono">{tool.name}</div>
                <ChevronRight className="size-3.5 text-faint" />
              </div>
              <p className="text-[11px] text-muted mt-1 line-clamp-2">{tool.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {tool.permission && (
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${permColor(tool.permission)}`}>
                    {tool.permission}
                  </span>
                )}
              </div>
            </motion.button>
          ))}
          {!tools && [...Array(5)].map((_, i) => <div key={i} className="skeleton h-20 rounded-xl" />)}
        </div>

        {/* Execution panel + history */}
        <div className="lg:col-span-3 space-y-4">
          {/* Execution form */}
          <AnimatePresence>
            {selectedTool ? (
              <motion.div
                key={selectedTool.name}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="card p-5"
              >
                <h2 className="font-medium mb-1 font-mono">{selectedTool.name}</h2>
                <p className="text-[12px] text-muted mb-4">{selectedTool.description}</p>

                {/* Parameters */}
                {selectedTool.parameters?.properties && (
                  <div className="mb-3">
                    <div className="text-[11px] font-medium text-faint mb-1.5">Parameters</div>
                    <div className="text-[11px] space-y-1">
                      {Object.entries(selectedTool.parameters.properties).map(([name, schema]: [string, any]) => (
                        <div key={name} className="flex gap-2">
                          <span className="font-mono text-accent">{name}</span>
                          <span className="text-faint">{schema.type}</span>
                          {schema.description && <span className="text-faint">— {schema.description}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="mb-3">
                  <div className="text-[11px] font-medium text-faint mb-1.5">Arguments (JSON)</div>
                  <textarea
                    value={argsJson}
                    onChange={(e) => setArgsJson(e.target.value)}
                    rows={5}
                    className="w-full rounded-lg border border-border bg-surface-2 p-3 text-[12px] font-mono outline-none focus:border-accent/60 resize-none"
                  />
                </div>

                <button
                  onClick={() => execMut.mutate()}
                  disabled={execMut.isPending || !workspace}
                  className="flex items-center gap-2 rounded-lg bg-accent/90 px-4 py-2 text-[13px] font-medium text-white hover:bg-accent disabled:opacity-50"
                >
                  <Play className="size-3.5" />
                  {execMut.isPending ? "Executing…" : "Execute"}
                </button>

                {execMut.isError && (
                  <div className="mt-3 rounded-lg bg-red/10 p-3 text-[12px] text-red">
                    {(execMut.error as Error).message}
                  </div>
                )}

                {lastResult && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="mt-3 rounded-lg border border-green/30 bg-green/5 p-3"
                  >
                    <div className="text-[11px] font-medium text-green mb-1">Result</div>
                    <pre className="text-[11px] font-mono text-muted whitespace-pre-wrap break-all">
                      {JSON.stringify(lastResult.result, null, 2)}
                    </pre>
                  </motion.div>
                )}
              </motion.div>
            ) : (
              <div className="card grid place-items-center p-12 text-center">
                <Wrench className="size-10 text-faint mb-3" />
                <p className="text-[13px] text-muted">Select a tool to execute it.</p>
              </div>
            )}
          </AnimatePresence>

          {/* Execution history */}
          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <Clock className="size-3.5 text-faint" /> Recent Executions
            </h2>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {history?.slice(0, 20).map((exec: any) => (
                <div key={exec.id} className="flex items-center gap-3 text-[12px]">
                  {exec.status === "ok" ? (
                    <CheckCircle className="size-3.5 text-green shrink-0" />
                  ) : (
                    <XCircle className="size-3.5 text-red shrink-0" />
                  )}
                  <span className="font-mono text-accent w-32 truncate shrink-0">{exec.tool}</span>
                  <span className="text-faint truncate flex-1">{exec.caller}</span>
                  <span className={`font-medium shrink-0 ${STATUS_STYLE[exec.status] ?? "text-muted"}`}>
                    {exec.duration_ms.toFixed(0)}ms
                  </span>
                </div>
              ))}
              {!history?.length && (
                <p className="text-[12px] text-faint">No executions yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
