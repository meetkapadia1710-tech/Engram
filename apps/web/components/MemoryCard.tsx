"use client";

import { motion } from "framer-motion";
import { Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Memory } from "@/lib/types";

export const TYPE_COLORS: Record<string, string> = {
  note: "text-accent bg-accent-soft",
  conversation: "text-cyan bg-cyan/10",
  document: "text-green bg-green/10",
  code: "text-amber bg-amber/10",
  bookmark: "text-pink bg-pink/10",
  task: "text-amber bg-amber/10",
};

export function typeBadge(type: string) {
  return TYPE_COLORS[type] ?? "text-muted bg-surface-2";
}

export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function MemoryCard({
  memory,
  score,
  index = 0,
}: {
  memory: Memory;
  score?: number;
  index?: number;
}) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => api.deleteMemory(memory.id),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: Math.min(index * 0.04, 0.3) }}
      className="card group p-4"
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${typeBadge(memory.type)}`}
        >
          {memory.type.replace(/_/g, " ")}
        </span>
        <span className="text-[11px] text-faint">{timeAgo(memory.created_at)}</span>
        {typeof score === "number" && (
          <span className="ml-auto font-mono text-[11px] text-accent">
            {(score * 100).toFixed(0)}%
          </span>
        )}
        <button
          onClick={() => del.mutate()}
          title="Forget this memory"
          className={`text-faint opacity-0 transition hover:text-pink group-hover:opacity-100 ${
            typeof score === "number" ? "" : "ml-auto"
          }`}
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>

      <h3 className="mb-1 line-clamp-1 text-[13.5px] font-medium">{memory.title}</h3>
      <p className="line-clamp-2 text-[12.5px] leading-relaxed text-muted">
        {memory.summary || memory.content}
      </p>

      {(memory.entities.length > 0 || memory.tags.length > 0) && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {memory.entities.slice(0, 4).map((e) => (
            <span
              key={e.id}
              className="rounded border border-border px-1.5 py-0.5 text-[10px] text-faint"
            >
              {e.name}
            </span>
          ))}
          {memory.tags.slice(0, 3).map((t) => (
            <span key={t} className="text-[10px] text-accent/80">
              #{t}
            </span>
          ))}
        </div>
      )}
    </motion.article>
  );
}
