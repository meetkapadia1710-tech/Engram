"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";
import { MemoryCard } from "@/components/MemoryCard";
import type { Memory } from "@/lib/types";

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86400_000);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "Today";
  if (same(d, yesterday)) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

export default function TimelinePage() {
  const { workspace } = useWorkspace();
  const [typeFilter, setTypeFilter] = useState<string>("");

  const { data: types } = useQuery({ queryKey: ["types"], queryFn: api.memoryTypes });
  const { data: memories } = useQuery({
    queryKey: ["timeline", workspace?.id, typeFilter],
    queryFn: () =>
      api.listMemories(workspace!.id, {
        limit: 200,
        type: typeFilter || undefined,
      }),
    enabled: !!workspace,
  });

  const groups = useMemo(() => {
    const map = new Map<string, Memory[]>();
    for (const m of memories ?? []) {
      const key = dayLabel(m.created_at);
      map.set(key, [...(map.get(key) ?? []), m]);
    }
    return [...map.entries()];
  }, [memories]);

  const usedTypes = useMemo(
    () => (types ?? []).filter((t) => (memories ?? []).some((m) => m.type === t) || t === typeFilter),
    [types, memories, typeFilter],
  );

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Timeline</h1>
        <p className="mt-1 text-[13px] text-muted">
          Every memory, newest first — grouped by the day it was formed.
        </p>
      </header>

      <div className="mb-6 flex flex-wrap gap-1.5">
        <button
          onClick={() => setTypeFilter("")}
          className={`rounded-full px-3 py-1 text-[11.5px] transition ${
            typeFilter === ""
              ? "bg-accent-soft text-accent"
              : "border border-border text-muted hover:border-border-strong"
          }`}
        >
          All
        </button>
        {usedTypes.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(t)}
            className={`rounded-full px-3 py-1 text-[11.5px] capitalize transition ${
              typeFilter === t
                ? "bg-accent-soft text-accent"
                : "border border-border text-muted hover:border-border-strong"
            }`}
          >
            {t.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      {memories === undefined && (
        <div className="flex flex-col gap-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="skeleton h-24" />
          ))}
        </div>
      )}

      {memories && memories.length === 0 && (
        <div className="card grid place-items-center p-12">
          <p className="text-[13px] text-muted">The timeline is empty — nothing remembered yet.</p>
        </div>
      )}

      <div className="relative flex flex-col gap-8 border-l border-border pl-6">
        {groups.map(([day, mems], gi) => (
          <motion.section
            key={day}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25, delay: gi * 0.05 }}
          >
            <div className="relative mb-3">
              <span className="absolute -left-[31px] top-1 size-2.5 rounded-full bg-accent" />
              <h2 className="text-[13px] font-semibold">{day}</h2>
              <span className="text-[11px] text-faint">
                {mems.length} memor{mems.length === 1 ? "y" : "ies"}
              </span>
            </div>
            <div className="flex flex-col gap-3">
              {mems.map((m, i) => (
                <MemoryCard key={m.id} memory={m} index={i} />
              ))}
            </div>
          </motion.section>
        ))}
      </div>
    </div>
  );
}
