"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Search as SearchIcon, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";
import { MemoryCard } from "@/components/MemoryCard";

const MODES = [
  { id: "hybrid", label: "Hybrid" },
  { id: "vector", label: "Semantic" },
  { id: "keyword", label: "Keyword" },
];

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-20 text-[10px] text-faint">{label}</span>
      <div className="h-1 flex-1 overflow-hidden rounded bg-surface-2">
        <div
          className="h-full rounded bg-accent/70"
          style={{ width: `${Math.min(value * 100, 100)}%` }}
        />
      </div>
      <span className="w-8 text-right font-mono text-[10px] text-faint">
        {value.toFixed(2)}
      </span>
    </div>
  );
}

function SearchInner() {
  const params = useSearchParams();
  const { workspace } = useWorkspace();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [submitted, setSubmitted] = useState(params.get("q") ?? "");
  const [mode, setMode] = useState("hybrid");
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data: results, isFetching } = useQuery({
    queryKey: ["search", workspace?.id, submitted, mode],
    queryFn: () => api.search(workspace!.id, { query: submitted, mode, limit: 20 }),
    enabled: !!workspace && submitted.trim().length > 0,
  });

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Search your memory</h1>
        <p className="mt-1 text-[13px] text-muted">
          BM25 + vector similarity, fused with RRF and re-ranked by importance, recency, and
          graph connectivity.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query);
        }}
        className="card mb-4 flex items-center gap-3 px-4 py-1.5 focus-within:border-accent/50"
      >
        <SearchIcon className="size-4 shrink-0 text-faint" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='Try "what did I learn about Docker?"'
          className="w-full bg-transparent py-2.5 text-[14px] outline-none placeholder:text-faint"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="rounded-lg bg-accent/90 px-3.5 py-1.5 text-[12.5px] font-medium text-white transition hover:bg-accent disabled:opacity-40"
        >
          Search
        </button>
      </form>

      <div className="mb-6 flex gap-1.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            className={`rounded-full px-3 py-1 text-[11.5px] transition ${
              mode === m.id
                ? "bg-accent-soft text-accent"
                : "border border-border text-muted hover:border-border-strong"
            }`}
          >
            {m.label}
          </button>
        ))}
        {isFetching && (
          <span className="ml-2 flex items-center gap-1.5 text-[11.5px] text-faint">
            <Sparkles className="size-3.5 animate-pulse" /> searching…
          </span>
        )}
      </div>

      {results && results.length === 0 && (
        <div className="card grid place-items-center p-12">
          <p className="text-[13px] text-muted">Nothing matched — Engram hasn&apos;t learned that yet.</p>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {results?.map((r, i) => (
          <div key={r.memory.id}>
            <div
              onClick={() => setExpanded(expanded === r.memory.id ? null : r.memory.id)}
              className="cursor-pointer"
            >
              <MemoryCard memory={r.memory} score={r.score} index={i} />
            </div>
            {expanded === r.memory.id && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                className="mx-3 rounded-b-xl border border-t-0 border-border bg-surface-2/50 px-4 py-3"
              >
                <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-faint">
                  Ranking breakdown
                </div>
                <div className="flex flex-col gap-1.5">
                  {Object.entries(r.components).map(([k, v]) => (
                    <ScoreBar key={k} label={k} value={v} />
                  ))}
                </div>
              </motion.div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchInner />
    </Suspense>
  );
}
