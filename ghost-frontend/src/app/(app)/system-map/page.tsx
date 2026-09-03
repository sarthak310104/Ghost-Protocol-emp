"use client";

import { useEffect, useMemo, useState } from "react";
import { api, GraphEdge, ApiError } from "@/lib/api";
import { layoutGraph, LayoutNode } from "@/lib/graphLayout";

const NODE_W = 120;
const NODE_H = 44;

function edgeDeviation(e: GraphEdge): "critical" | "warn" | "ok" {
  if (!e.has_reference_baseline || e.reference_latency_ms <= 0) return "ok";
  const ratio = e.current_latency_ms_p99 / e.reference_latency_ms;
  if (ratio > 2) return "critical";
  if (ratio > 1.3) return "warn";
  return "ok";
}

const EDGE_COLOR: Record<string, string> = {
  critical: "#c94a3a",
  warn: "#d4a13d",
  ok: "#3c3932",
};

function nodeCenter(n: LayoutNode) {
  return { cx: n.x + NODE_W / 2, cy: n.y + NODE_H / 2 };
}

export default function SystemMapPage() {
  const [edges, setEdges] = useState<GraphEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .graph()
      .then(setEdges)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load graph"));
  }, []);

  const layout = useMemo(() => (edges ? layoutGraph(edges) : null), [edges]);

  const edgesByNode = useMemo(() => {
    if (!edges || !layout) return [];
    const byName = new Map(layout.nodes.map((n) => [n.name, n]));
    return edges
      .map((e) => {
        const from = byName.get(e.caller);
        const to = byName.get(e.callee);
        if (!from || !to) return null;
        return { edge: e, from: nodeCenter(from), to: nodeCenter(to), deviation: edgeDeviation(e) };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
  }, [edges, layout]);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em] flex items-center gap-2">
          Live system map
          <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
        </div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">System Map</h1>
        <div className="text-ghost-muted mt-2">
          Every service Ghost has discovered from real traffic, laid out by call depth -- never manually
          configured.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {edges === null && <div className="text-ghost-dim text-xs">Loading...</div>}
      {edges !== null && edges.length === 0 && (
        <div className="text-ghost-dim text-xs">No topology discovered yet -- send some traffic first.</div>
      )}

      {layout && edges && edges.length > 0 && (
        <div className="relative bg-surface border border-hud-bright/40 rounded-md overflow-auto">
          <span className="pointer-events-none absolute top-3 left-3 w-5 h-5 border-t border-l border-hud-bright opacity-70 z-10" />
          <span className="pointer-events-none absolute bottom-3 right-3 w-5 h-5 border-b border-r border-hud-bright opacity-70 z-10" />

          <svg width={layout.width} height={layout.height} className="block">
            {edgesByNode.map(({ edge, from, to, deviation }) => (
              <g key={`${edge.caller}->${edge.callee}`}>
                <line
                  x1={from.cx} y1={from.cy} x2={to.cx} y2={to.cy}
                  stroke={EDGE_COLOR[deviation]}
                  strokeWidth={deviation === "critical" ? 2 : 1.2}
                />
                <circle r={deviation === "ok" ? 2 : 2.6} fill={EDGE_COLOR[deviation]}>
                  <animateMotion
                    dur={deviation === "critical" ? "1.1s" : "2s"}
                    repeatCount="indefinite"
                    path={`M${from.cx},${from.cy} L${to.cx},${to.cy}`}
                  />
                </circle>
              </g>
            ))}

            {layout.nodes.map((n) => {
              const incoming = edgesByNode.filter((e) => e.edge.callee === n.name);
              const worst = incoming.some((e) => e.deviation === "critical")
                ? "critical"
                : incoming.some((e) => e.deviation === "warn")
                ? "warn"
                : "ok";
              return (
                <g key={n.name}>
                  <rect
                    x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx={5}
                    fill="#10100e"
                    stroke={worst === "critical" ? "#6a3029" : "#3c3932"}
                  />
                  <circle
                    cx={n.x + 14} cy={n.y + NODE_H / 2} r={3}
                    fill={worst === "critical" ? "#c94a3a" : worst === "warn" ? "#d4a13d" : "#55bd78"}
                  >
                    {worst === "critical" && (
                      <animate attributeName="opacity" values="1;0.3;1" dur="1.2s" repeatCount="indefinite" />
                    )}
                  </circle>
                  <text x={n.x + 26} y={n.y + NODE_H / 2 + 4} fill="#d1cabe" fontSize={11} fontFamily="IBM Plex Mono, monospace">
                    {n.name}
                  </text>
                </g>
              );
            })}
          </svg>

          <div className="absolute right-4 bottom-4 flex gap-4 text-[9px] text-ghost-muted bg-bg/60 px-2 py-1 rounded">
            <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-status-green" />healthy</span>
            <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-status-amber" />deviation</span>
            <span className="flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-status-red" />critical</span>
          </div>
        </div>
      )}
    </>
  );
}