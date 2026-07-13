"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useWorkspace } from "@/app/providers";
import type { GraphData, GraphNode } from "@/lib/types";

/**
 * Force-directed graph explorer — hand-rolled physics (repulsion + spring +
 * centering) rendered as SVG. No canvas/d3 dependency; ~150 nodes stay smooth.
 */

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const KIND_COLOR: Record<string, string> = {
  memory: "#7c8cff",
  entity: "#22d3ee",
};

function useSimulation(data: GraphData | undefined, width: number, height: number) {
  const [nodes, setNodes] = useState<SimNode[]>([]);
  const frame = useRef<number>(0);

  useEffect(() => {
    if (!data) return;
    const sim: SimNode[] = data.nodes.map((n, i) => ({
      ...n,
      x: width / 2 + 180 * Math.cos((2 * Math.PI * i) / data.nodes.length),
      y: height / 2 + 180 * Math.sin((2 * Math.PI * i) / data.nodes.length),
      vx: 0,
      vy: 0,
    }));
    const byId = new Map(sim.map((n) => [n.id, n]));
    let ticks = 0;

    function tick() {
      ticks += 1;
      // repulsion
      for (let i = 0; i < sim.length; i++) {
        for (let j = i + 1; j < sim.length; j++) {
          const a = sim[i], b = sim[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
          const f = 1400 / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * f; a.vy += (dy / d) * f;
          b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
        }
      }
      // springs
      for (const e of data!.edges) {
        const a = byId.get(e.source), b = byId.get(e.target);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 90) * 0.012 * (0.5 + e.weight);
        a.vx += (dx / d) * f; a.vy += (dy / d) * f;
        b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
      }
      // centering + integrate
      for (const n of sim) {
        n.vx += (width / 2 - n.x) * 0.004;
        n.vy += (height / 2 - n.y) * 0.004;
        n.vx *= 0.82; n.vy *= 0.82;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(24, Math.min(width - 24, n.x));
        n.y = Math.max(24, Math.min(height - 24, n.y));
      }
      setNodes([...sim]);
      if (ticks < 220) frame.current = requestAnimationFrame(tick);
    }
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [data, width, height]);

  return nodes;
}

export default function GraphPage() {
  const { workspace } = useWorkspace();
  const [selected, setSelected] = useState<SimNode | null>(null);
  const width = 920, height = 560;

  const { data } = useQuery({
    queryKey: ["graph", workspace?.id],
    queryFn: () => api.graph(workspace!.id),
    enabled: !!workspace,
  });

  const nodes = useSimulation(data, width, height);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Knowledge graph</h1>
        <p className="mt-1 text-[13px] text-muted">
          <span className="text-accent">●</span> memories ·{" "}
          <span className="text-cyan">●</span> entities — edges are detected
          relationships (related_to, mentions, duplicate_of).
        </p>
      </header>

      <div className="card relative overflow-hidden">
        {!data && <div className="skeleton h-[560px] w-full" />}
        {data && data.nodes.length === 0 && (
          <div className="grid h-[560px] place-items-center">
            <p className="text-[13px] text-muted">Add a few memories and the graph will grow.</p>
          </div>
        )}
        {data && data.nodes.length > 0 && (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="h-auto w-full"
            onClick={() => setSelected(null)}
          >
            {data.edges.map((e, i) => {
              const a = byId.get(e.source), b = byId.get(e.target);
              if (!a || !b) return null;
              return (
                <line
                  key={i}
                  x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke="#2c3140"
                  strokeWidth={0.6 + e.weight * 1.6}
                  strokeOpacity={0.7}
                />
              );
            })}
            {nodes.map((n) => {
              const r = n.kind === "memory" ? 7 + (n.importance ?? 0.5) * 6 : 4 + Math.min(n.degree, 8);
              const isSel = selected?.id === n.id;
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y})`}
                  onClick={(ev) => { ev.stopPropagation(); setSelected(n); }}
                  className="cursor-pointer"
                >
                  <circle
                    r={r}
                    fill={KIND_COLOR[n.kind]}
                    fillOpacity={isSel ? 1 : 0.85}
                    stroke={isSel ? "#e8eaf0" : "transparent"}
                    strokeWidth={1.5}
                  />
                  {(n.degree > 2 || isSel) && (
                    <text
                      y={-r - 5}
                      textAnchor="middle"
                      className="pointer-events-none select-none"
                      fill="#8b91a3"
                      fontSize={10}
                    >
                      {n.label.length > 26 ? n.label.slice(0, 26) + "…" : n.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        )}

        {selected && (
          <div className="glass absolute right-4 top-4 w-64 rounded-xl p-4">
            <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-faint">
              {selected.kind} · {selected.type}
            </div>
            <div className="text-[13px] font-medium">{selected.label}</div>
            <div className="mt-2 text-[11.5px] text-muted">
              {selected.kind === "memory"
                ? `importance ${(selected.importance ?? 0).toFixed(2)} · ${selected.degree} connection${selected.degree === 1 ? "" : "s"}`
                : `${selected.mentions ?? 0} mention${(selected.mentions ?? 0) === 1 ? "" : "s"} · ${selected.degree} connection${selected.degree === 1 ? "" : "s"}`}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
