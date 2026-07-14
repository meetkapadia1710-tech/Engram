"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, Play, ChevronDown, ChevronRight, CheckCircle, AlertCircle, Clock, Users, MessageSquare, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const AGENT_COLORS: Record<string, string> = {
  orchestrator: "bg-accent/20 text-accent",
  research: "bg-cyan/20 text-cyan",
  coding: "bg-green/20 text-green",
  planning: "bg-amber/20 text-amber",
  memory: "bg-purple/20 text-purple",
  analyst: "bg-pink/20 text-pink",
};

const KIND_ICONS: Record<string, string> = {
  plan: "📋", finding: "🔍", vote: "🗳️", debate: "⚔️", merge: "🔀",
};

export default function AgentsPage() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const [goal, setGoal] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);

  const { data: team } = useQuery({
    queryKey: ["agents-team"],
    queryFn: () => api.listAgentTeam(),
  });

  const { data: runs } = useQuery({
    queryKey: ["agent-runs", workspace?.id],
    queryFn: () => api.listAgentRuns(workspace!.id),
    enabled: !!workspace,
    refetchInterval: 5000,
  });

  const { data: expandedRunData } = useQuery({
    queryKey: ["agent-run", workspace?.id, expandedRun],
    queryFn: () => api.getAgentRun(workspace!.id, expandedRun!),
    enabled: !!workspace && !!expandedRun,
    refetchInterval: (q) => q.state.data?.status === "running" ? 2000 : false,
  });

  const runMut = useMutation({
    mutationFn: () =>
      api.startAgentRun(workspace!.id, goal.trim(), selectedAgents.length ? selectedAgents : undefined),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["agent-runs"] });
      setGoal("");
      setExpandedRun(data.id);
    },
  });

  const toggleAgent = (name: string) => {
    setSelectedAgents((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  };

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8">
        <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <Bot className="size-5 text-accent" /> Multi-Agent Orchestrator
        </h1>
        <p className="mt-1 text-[13px] text-muted">
          Collaborate AI agents to research, debate, vote, and synthesise conclusions from memory.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: Run form */}
        <div className="lg:col-span-1 space-y-4">
          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3">New Agent Run</h2>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="What do you want the agents to research? e.g. 'Summarise all decisions made about the auth system'"
              rows={4}
              className="w-full rounded-lg border border-border bg-surface-2 p-3 text-[13px] outline-none focus:border-accent/60 resize-none"
            />

            {/* Agent selector */}
            <div className="mt-3">
              <div className="text-[11px] font-medium text-faint mb-2">Team (leave empty for default)</div>
              <div className="flex flex-wrap gap-1.5">
                {team?.agents.map((agent: any) => (
                  <button
                    key={agent.name}
                    onClick={() => toggleAgent(agent.name)}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition border ${
                      selectedAgents.includes(agent.name)
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border text-muted hover:border-border-strong"
                    }`}
                  >
                    {agent.role}
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={() => runMut.mutate()}
              disabled={!goal.trim() || runMut.isPending || !workspace}
              className="mt-4 w-full flex items-center justify-center gap-2 rounded-lg bg-accent/90 py-2.5 text-[13px] font-medium text-white transition hover:bg-accent disabled:opacity-50"
            >
              {runMut.isPending ? (
                <><Loader2 className="size-4 animate-spin" /> Running…</>
              ) : (
                <><Play className="size-4" /> Start Run</>
              )}
            </button>
          </div>

          {/* Agent roster */}
          <div className="card p-5">
            <h2 className="text-[13px] font-medium mb-3 flex items-center gap-2">
              <Users className="size-3.5 text-faint" /> Agent Roster
            </h2>
            <div className="space-y-2">
              {team?.agents.map((agent: any) => (
                <div key={agent.name} className="flex items-center gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${AGENT_COLORS[agent.name] ?? "bg-surface-2 text-muted"}`}>
                    {agent.role}
                  </span>
                  <span className="text-[11px] text-faint truncate">{agent.focus}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right: Run history + collaboration timeline */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-[13px] font-medium text-muted">Recent Runs</h2>
          {runs?.map((run: any) => (
            <motion.div key={run.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="card overflow-hidden">
              <button
                onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}
                className="w-full flex items-center gap-3 p-4 text-left hover:bg-surface-2/40 transition"
              >
                <StatusIcon status={run.status} />
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium truncate">{run.goal}</div>
                  <div className="text-[11px] text-faint mt-0.5">
                    {new Date(run.started_at).toLocaleString()} · {run.agents?.join(", ")}
                  </div>
                </div>
                {expandedRun === run.id ? (
                  <ChevronDown className="size-4 text-faint shrink-0" />
                ) : (
                  <ChevronRight className="size-4 text-faint shrink-0" />
                )}
              </button>

              <AnimatePresence>
                {expandedRun === run.id && expandedRunData && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-border"
                  >
                    {/* Conclusion */}
                    {expandedRunData.conclusion && (
                      <div className="p-4 bg-accent/5 border-b border-border">
                        <div className="text-[11px] font-semibold text-accent mb-1">🔀 Conclusion</div>
                        <p className="text-[12.5px] text-muted">{expandedRunData.conclusion}</p>
                      </div>
                    )}
                    {/* Messages timeline */}
                    <div className="p-4 space-y-2 max-h-80 overflow-y-auto">
                      {expandedRunData.messages?.map((msg: any) => (
                        <div key={msg.seq} className="flex gap-2.5">
                          <span className={`mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-medium h-fit shrink-0 ${AGENT_COLORS[msg.sender] ?? "bg-surface-2 text-muted"}`}>
                            {msg.sender}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-0.5">
                              <span className="text-[10px] text-faint">{KIND_ICONS[msg.kind] ?? "💬"} {msg.kind}</span>
                              {msg.recipient !== "all" && (
                                <span className="text-[10px] text-faint">→ {msg.recipient}</span>
                              )}
                            </div>
                            <p className="text-[12px] text-muted">{msg.content}</p>
                          </div>
                        </div>
                      ))}
                      {expandedRunData.status === "running" && (
                        <div className="flex items-center gap-2 text-[12px] text-faint">
                          <Loader2 className="size-3.5 animate-spin" /> Agents collaborating…
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          ))}
          {!runs && (
            [...Array(3)].map((_, i) => <div key={i} className="skeleton h-16 rounded-xl" />)
          )}
          {runs?.length === 0 && (
            <div className="card grid place-items-center p-12 text-center">
              <Bot className="size-10 text-faint mb-3" />
              <p className="text-[13px] text-muted">No runs yet. Start your first agent collaboration above.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "ok") return <CheckCircle className="size-4 text-green shrink-0" />;
  if (status === "running") return <Loader2 className="size-4 text-accent animate-spin shrink-0" />;
  return <AlertCircle className="size-4 text-red shrink-0" />;
}
