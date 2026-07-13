"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Brain,
  Clock,
  Command,
  LayoutDashboard,
  Plus,
  Search,
  Settings,
  Waypoints,
} from "lucide-react";
import { useWorkspace } from "@/app/providers";
import { CommandPalette } from "./CommandPalette";
import { AddMemoryDialog } from "./AddMemoryDialog";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/search", label: "Search", icon: Search },
  { href: "/graph", label: "Graph", icon: Waypoints },
  { href: "/timeline", label: "Timeline", icon: Clock },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { workspace } = useWorkspace();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="relative z-10 flex min-h-screen">
      <aside className="glass sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-border px-4 py-6">
        <Link href="/" className="mb-8 flex items-center gap-2.5 px-2">
          <span className="grid size-8 place-items-center rounded-lg bg-accent-soft">
            <Brain className="size-4.5 text-accent" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Engram</span>
        </Link>

        <button
          onClick={() => setAddOpen(true)}
          className="mb-6 flex items-center justify-center gap-2 rounded-lg bg-accent/90 px-3 py-2 text-[13px] font-medium text-white transition hover:bg-accent"
        >
          <Plus className="size-4" /> New memory
        </button>

        <nav className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition ${
                  active
                    ? "bg-surface-2 text-text"
                    : "text-muted hover:bg-surface-2/60 hover:text-text"
                }`}
              >
                <Icon className="size-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <button
          onClick={() => setPaletteOpen(true)}
          className="mt-auto flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-[12px] text-faint transition hover:border-border-strong hover:text-muted"
        >
          <Command className="size-3.5" />
          Command palette
          <kbd className="ml-auto rounded border border-border px-1.5 py-0.5 font-mono text-[10px]">
            ⌘K
          </kbd>
        </button>

        <div className="mt-4 px-2 text-[11px] text-faint">
          {workspace ? `Workspace · ${workspace.name}` : "Connecting…"}
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-8 py-8">{children}</main>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onAddMemory={() => {
          setPaletteOpen(false);
          setAddOpen(true);
        }}
      />
      <AddMemoryDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
