"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Server, ShieldCheck, Cpu } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border py-3 last:border-0">
      <span className="text-[13px] text-muted">{label}</span>
      <span className="text-[13px]">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { workspace } = useWorkspace();
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 10_000, // Supermemory reachability can change between page loads
  });

  return (
    <div className="mx-auto max-w-2xl">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-[13px] text-muted">Instance, providers, and workspace.</p>
      </header>

      <div className="card mb-4 p-5">
        <h2 className="mb-2 flex items-center gap-2 text-[13px] font-medium">
          <Server className="size-4 text-accent" /> Instance
        </h2>
        <Row
          label="API status"
          value={
            !health ? (
              "connecting…"
            ) : health.status === "ok" ? (
              <span className="flex items-center gap-1.5 text-green">
                <CheckCircle2 className="size-3.5" /> healthy · v{health.version}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-amber">
                <AlertTriangle className="size-3.5" /> degraded · v{health.version}
              </span>
            )
          }
        />
        <Row label="API URL" value={<code className="font-mono text-[12px]">{process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}</code>} />
        <Row label="OpenAPI docs" value={<a className="text-accent hover:underline" href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/docs`} target="_blank" rel="noreferrer">/docs ↗</a>} />
      </div>

      <div className="card mb-4 p-5">
        <h2 className="mb-2 flex items-center gap-2 text-[13px] font-medium">
          <Server className="size-4 text-accent" /> Supermemory Local
        </h2>
        <Row
          label="Reachable"
          value={
            !health ? (
              "…"
            ) : health.dependencies.supermemory.reachable ? (
              <span className="flex items-center gap-1.5 text-green">
                <CheckCircle2 className="size-3.5" /> yes
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-amber">
                <AlertTriangle className="size-3.5" /> no
              </span>
            )
          }
        />
        <Row label="URL" value={<code className="font-mono text-[12px]">{health?.dependencies.supermemory.url ?? "…"}</code>} />
        <Row label="Latency" value={health ? `${health.dependencies.supermemory.latency_ms}ms` : "…"} />
        {health && !health.dependencies.supermemory.reachable && (
          <p className="mt-3 text-[12px] leading-relaxed text-amber">
            {health.dependencies.supermemory.error ?? "Unreachable"} — memory creation, updates,
            deletes, and search all depend on Supermemory Local; start it and this page will
            recover automatically.
          </p>
        )}
      </div>

      <div className="card mb-4 p-5">
        <h2 className="mb-2 flex items-center gap-2 text-[13px] font-medium">
          <Cpu className="size-4 text-cyan" /> AI providers
        </h2>
        <Row label="Embeddings" value={<code className="font-mono text-[12px]">{health?.embedding_provider ?? "…"}</code>} />
        <Row label="Generation" value={<code className="font-mono text-[12px]">{health?.generation_provider ?? "…"}</code>} />
        <p className="mt-3 text-[12px] leading-relaxed text-faint">
          Switch providers with <code className="font-mono">ENGRAM_EMBEDDING_PROVIDER</code> /{" "}
          <code className="font-mono">ENGRAM_GENERATION_PROVIDER</code> (local, openai,
          anthropic, gemini, ollama) — no code changes required. The{" "}
          <code className="font-mono">local</code> provider needs no API keys.
        </p>
      </div>

      <div className="card p-5">
        <h2 className="mb-2 flex items-center gap-2 text-[13px] font-medium">
          <ShieldCheck className="size-4 text-green" /> Workspace
        </h2>
        <Row label="Name" value={workspace?.name ?? "…"} />
        <Row label="ID" value={<code className="font-mono text-[12px]">{workspace?.id ?? "…"}</code>} />
        <Row label="Auth mode" value="open (dev) — set ENGRAM_API_KEYS to lock down" />
      </div>
    </div>
  );
}
