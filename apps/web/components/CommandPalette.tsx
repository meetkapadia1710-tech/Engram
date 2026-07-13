"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Clock,
  LayoutDashboard,
  Plus,
  Search,
  Settings,
  Waypoints,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

interface Props {
  open: boolean;
  onClose: () => void;
  onAddMemory: () => void;
}

export function CommandPalette({ open, onClose, onAddMemory }: Props) {
  const router = useRouter();
  const { workspace } = useWorkspace();
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQ("");
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  const { data: hits } = useQuery({
    queryKey: ["palette-search", workspace?.id, q],
    queryFn: () => api.search(workspace!.id, { query: q, limit: 5 }),
    enabled: open && !!workspace && q.trim().length > 1,
  });

  const actions = [
    { label: "New memory", icon: Plus, run: onAddMemory },
    { label: "Go to Dashboard", icon: LayoutDashboard, run: () => router.push("/") },
    { label: "Go to Search", icon: Search, run: () => router.push("/search") },
    { label: "Go to Graph", icon: Waypoints, run: () => router.push("/graph") },
    { label: "Go to Timeline", icon: Clock, run: () => router.push("/timeline") },
    { label: "Go to Settings", icon: Settings, run: () => router.push("/settings") },
  ].filter((a) => a.label.toLowerCase().includes(q.toLowerCase()));

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className="glass mx-auto mt-[14vh] w-full max-w-xl overflow-hidden rounded-2xl shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-border px-4">
              <Search className="size-4 text-faint" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search memories or type a command…"
                className="w-full bg-transparent py-3.5 text-sm outline-none placeholder:text-faint"
              />
              <kbd className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-faint">
                esc
              </kbd>
            </div>

            <div className="max-h-[50vh] overflow-y-auto p-2">
              {actions.length > 0 && (
                <div className="mb-1 px-2 pt-1 text-[10px] font-medium uppercase tracking-widest text-faint">
                  Actions
                </div>
              )}
              {actions.map(({ label, icon: Icon, run }) => (
                <button
                  key={label}
                  onClick={() => {
                    run();
                    onClose();
                  }}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] text-muted transition hover:bg-surface-2 hover:text-text"
                >
                  <Icon className="size-4" />
                  {label}
                </button>
              ))}

              {hits && hits.length > 0 && (
                <>
                  <div className="mb-1 px-2 pt-3 text-[10px] font-medium uppercase tracking-widest text-faint">
                    Memories
                  </div>
                  {hits.map((h) => (
                    <button
                      key={h.memory.id}
                      onClick={() => {
                        router.push(`/search?q=${encodeURIComponent(q)}`);
                        onClose();
                      }}
                      className="flex w-full flex-col gap-0.5 rounded-lg px-3 py-2 text-left transition hover:bg-surface-2"
                    >
                      <span className="truncate text-[13px]">{h.memory.title}</span>
                      <span className="truncate text-[11px] text-faint">
                        {h.memory.content.slice(0, 90)}
                      </span>
                    </button>
                  ))}
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
