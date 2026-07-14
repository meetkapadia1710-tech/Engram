"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  Store, Search, Download, Trash2, RefreshCw, CheckCircle,
  Shield, Zap, Package, ChevronRight, Star, Lock
} from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const KIND_ICONS: Record<string, string> = {
  app: "🧩", plugin: "🔌", workflow: "⚡", prompt_pack: "✨",
  knowledge_pack: "📚", template: "📋",
};

const KIND_COLORS: Record<string, string> = {
  app: "bg-accent/10 text-accent",
  plugin: "bg-cyan/10 text-cyan",
  workflow: "bg-green/10 text-green",
  prompt_pack: "bg-amber/10 text-amber",
  knowledge_pack: "bg-purple/10 text-purple",
  template: "bg-pink/10 text-pink",
};

export default function Marketplace() {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [selected, setSelected] = useState<any>(null);

  const { data: catalog } = useQuery({
    queryKey: ["catalog", kind, search],
    queryFn: () => api.listCatalog({ kind: kind || undefined, q: search || undefined }),
    staleTime: 30_000,
  });

  const { data: installed } = useQuery({
    queryKey: ["installed", workspace?.id],
    queryFn: () => api.listInstalled(workspace!.id),
    enabled: !!workspace,
  });

  const installedSlugs = new Set(
    installed?.map((i: any) => {
      const found = catalog?.items?.find((p: any) => p.id === i.plugin_id);
      return found?.slug;
    }) ?? []
  );

  const installMut = useMutation({
    mutationFn: (slug: string) => api.installPlugin(workspace!.id, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["installed"] }),
  });

  const uninstallMut = useMutation({
    mutationFn: (slug: string) => api.uninstallPlugin(workspace!.id, slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["installed"] }),
  });

  const kinds = ["", "app", "plugin", "workflow", "prompt_pack", "knowledge_pack"];

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Store className="size-5 text-accent" /> Marketplace
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            {catalog?.total ?? "…"} apps, plugins, and packs available
          </p>
        </div>
      </header>

      {/* Filters */}
      <div className="mb-6 flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search marketplace…"
            className="w-full rounded-lg border border-border bg-surface-2 pl-9 pr-3 py-2 text-[13px] outline-none focus:border-accent/60"
          />
        </div>
        <div className="flex gap-1.5">
          {kinds.map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition ${
                kind === k
                  ? "bg-accent text-white"
                  : "bg-surface-2 text-muted hover:text-text"
              }`}
            >
              {k ? k.replace("_", " ") : "All"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Catalog grid */}
        <div className="lg:col-span-2 grid gap-3 md:grid-cols-2 content-start">
          {catalog?.items?.map((plugin: any, i: number) => {
            const isInstalled = installedSlugs.has(plugin.slug);
            return (
              <motion.div
                key={plugin.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
                onClick={() => setSelected(plugin)}
                className={`card cursor-pointer p-5 transition hover:border-accent/40 ${
                  selected?.id === plugin.id ? "border-accent/60" : ""
                }`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl">{KIND_ICONS[plugin.kind] ?? "📦"}</span>
                    <div>
                      <div className="font-medium text-[13px]">{plugin.name}</div>
                      <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${KIND_COLORS[plugin.kind] ?? "bg-surface-2 text-muted"}`}>
                        {plugin.kind}
                      </span>
                    </div>
                  </div>
                  {isInstalled ? (
                    <span className="flex items-center gap-1 text-[11px] text-green">
                      <CheckCircle className="size-3.5" /> Installed
                    </span>
                  ) : plugin.first_party ? (
                    <span className="flex items-center gap-1 text-[11px] text-accent">
                      <Star className="size-3" /> Official
                    </span>
                  ) : null}
                </div>
                <p className="text-[12px] text-muted line-clamp-2">{plugin.description}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="text-[11px] text-faint">v{plugin.latest_version}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (isInstalled) uninstallMut.mutate(plugin.slug);
                      else installMut.mutate(plugin.slug);
                    }}
                    disabled={installMut.isPending || uninstallMut.isPending}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition ${
                      isInstalled
                        ? "bg-surface-2 text-muted hover:bg-red/10 hover:text-red"
                        : "bg-accent/90 text-white hover:bg-accent"
                    }`}
                  >
                    {isInstalled ? (
                      <><Trash2 className="size-3" /> Remove</>
                    ) : (
                      <><Download className="size-3" /> Install</>
                    )}
                  </button>
                </div>
              </motion.div>
            );
          })}
          {!catalog && (
            [...Array(6)].map((_, i) => (
              <div key={i} className="skeleton h-36 rounded-xl" />
            ))
          )}
        </div>

        {/* Detail panel */}
        <AnimatePresence>
          {selected && (
            <motion.div
              key={selected.id}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              className="card sticky top-8 p-6 h-fit"
            >
              <div className="text-4xl mb-3">{KIND_ICONS[selected.kind] ?? "📦"}</div>
              <h2 className="font-semibold">{selected.name}</h2>
              <p className="mt-2 text-[12px] text-muted">{selected.description}</p>

              <div className="mt-4 space-y-2">
                <div className="flex items-center gap-2 text-[12px]">
                  <Package className="size-3.5 text-faint" />
                  <span className="text-faint">Version</span>
                  <span className="ml-auto font-mono">{selected.latest_version}</span>
                </div>
                <div className="flex items-center gap-2 text-[12px]">
                  <Shield className="size-3.5 text-faint" />
                  <span className="text-faint">Author</span>
                  <span className="ml-auto">{selected.author || "Community"}</span>
                </div>
              </div>

              <div className="mt-4">
                <div className="text-[11px] font-medium text-faint mb-2 flex items-center gap-1">
                  <Lock className="size-3" /> Permissions requested
                </div>
                {/* Permissions from manifest */}
                <div className="flex flex-wrap gap-1.5">
                  {["memory.read", "search", "context"].map((p) => (
                    <span key={p} className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted">
                      {p}
                    </span>
                  ))}
                </div>
              </div>

              <button
                onClick={() => {
                  if (installedSlugs.has(selected.slug)) uninstallMut.mutate(selected.slug);
                  else installMut.mutate(selected.slug);
                }}
                className="mt-5 w-full rounded-lg bg-accent/90 py-2 text-[13px] font-medium text-white transition hover:bg-accent"
              >
                {installedSlugs.has(selected.slug) ? "Uninstall" : "Install"}
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
