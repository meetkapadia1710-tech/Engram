"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";

const QUICK_TYPES = ["note", "conversation", "document", "code", "bookmark", "task"];

export function AddMemoryDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { workspace } = useWorkspace();
  const qc = useQueryClient();
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [type, setType] = useState("note");
  const [tags, setTags] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      api.createMemory(workspace!.id, {
        content,
        title,
        type,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      qc.invalidateQueries();
      setContent("");
      setTitle("");
      setTags("");
      onClose();
    },
  });

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="glass w-full max-w-lg rounded-2xl p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">New memory</h2>
              <button onClick={onClose} className="text-faint transition hover:text-text">
                <X className="size-4" />
              </button>
            </div>

            <div className="mb-3 flex flex-wrap gap-1.5">
              {QUICK_TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  className={`rounded-full px-3 py-1 text-[11px] capitalize transition ${
                    type === t
                      ? "bg-accent-soft text-accent"
                      : "border border-border text-muted hover:border-border-strong"
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>

            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title (optional — auto-generated)"
              className="mb-2 w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none transition placeholder:text-faint focus:border-accent/60"
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="What should Engram remember?"
              rows={5}
              className="mb-2 w-full resize-none rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none transition placeholder:text-faint focus:border-accent/60"
            />
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="Tags, comma separated"
              className="mb-4 w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] outline-none transition placeholder:text-faint focus:border-accent/60"
            />

            {mutation.isError && (
              <p className="mb-3 text-[12px] text-pink">{String(mutation.error)}</p>
            )}

            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-lg px-4 py-2 text-[13px] text-muted transition hover:text-text"
              >
                Cancel
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={!content.trim() || !workspace || mutation.isPending}
                className="rounded-lg bg-accent/90 px-4 py-2 text-[13px] font-medium text-white transition hover:bg-accent disabled:opacity-40"
              >
                {mutation.isPending ? "Remembering…" : "Remember"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
