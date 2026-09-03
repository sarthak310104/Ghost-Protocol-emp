"use client";

import { useEffect, useState } from "react";
import { api, GraphEdge, ApiError } from "@/lib/api";

function latencyDeviationPct(e: GraphEdge): number | null {
  if (!e.has_reference_baseline || e.reference_latency_ms <= 0) return null;
  return Math.round(((e.current_latency_ms_p99 - e.reference_latency_ms) / e.reference_latency_ms) * 100);
}

function severityOf(pct: number | null): "critical" | "warn" | "ok" | "unknown" {
  if (pct === null) return "unknown";
  if (pct > 100) return "critical";
  if (pct > 30) return "warn";
  return "ok";
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "text-status-red",
  warn: "text-status-amber",
  ok: "text-status-green",
  unknown: "text-ghost-dim",
};

function EdgeRow({ e }: { e: GraphEdge }) {
  const [width, setWidth] = useState(0);
  const pct = latencyDeviationPct(e);
  const severity = severityOf(pct);
  const barTarget = Math.min(100, Math.max(0, pct ?? 0));

  useEffect(() => {
    const id = requestAnimationFrame(() => setWidth(barTarget));
    return () => cancelAnimationFrame(id);
  }, [barTarget]);

  return (
    <div className="bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        <span className="text-ghost-text text-[13px]">
          {e.caller} <span className="text-ghost-dim">→</span> {e.callee}
        </span>
        {severity === "critical" && (
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-status-red" />
          </span>
        )}
        <span className={`ml-auto text-[11px] ${SEVERITY_COLOR[severity]}`}>
          {pct === null ? "no baseline yet" : `${pct > 0 ? "+" : ""}${pct}% vs normal`}
        </span>
      </div>

      {pct !== null && (
        <div className="h-[3px] bg-[#1b1a17] mt-3 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-[width] duration-700 ease-out ${
              severity === "critical" ? "bg-status-red" : severity === "warn" ? "bg-status-amber" : "bg-status-green"
            }`}
            style={{
              width: `${width}%`,
              boxShadow: severity === "critical" ? "0 0 8px rgba(201,74,58,0.6)" : undefined,
            }}
          />
        </div>
      )}

      <div className="grid grid-cols-4 gap-4 mt-4">
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">p50 latency</div>
          <div className="text-ghost-text text-[13px] mt-1">{e.current_latency_ms_p50.toFixed(1)}ms</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">p99 latency</div>
          <div className="text-ghost-text text-[13px] mt-1">
            {e.current_latency_ms_p99.toFixed(1)}ms
            {e.has_reference_baseline && (
              <span className="text-ghost-dim text-[10px]"> / {e.reference_latency_ms.toFixed(1)}ms normal</span>
            )}
          </div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Error rate</div>
          <div className="text-ghost-text text-[13px] mt-1">
            {(e.current_error_rate * 100).toFixed(1)}%
            {e.has_reference_baseline && (
              <span className="text-ghost-dim text-[10px]"> / {(e.reference_error_rate * 100).toFixed(1)}% normal</span>
            )}
          </div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Samples</div>
          <div className="text-ghost-text text-[13px] mt-1">{e.sample_count}</div>
        </div>
      </div>
    </div>
  );
}

export default function BehaviorPage() {
  const [edges, setEdges] = useState<GraphEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .graph()
      .then(setEdges)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load graph"));
  }, []);

  const sorted = edges
    ? [...edges].sort((a, b) => (latencyDeviationPct(b) ?? -999) - (latencyDeviationPct(a) ?? -999))
    : null;

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em] flex items-center gap-2">
          Current vs normal
          <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
        </div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Behavior</h1>
        <div className="text-ghost-muted mt-2">
          Every call path's live latency and error rate, compared against its own learned baseline --
          sorted by how far off normal it currently is.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {sorted === null && <div className="text-ghost-dim text-xs">Loading...</div>}
      {sorted !== null && sorted.length === 0 && (
        <div className="text-ghost-dim text-xs">No edges discovered yet -- send some traffic first.</div>
      )}

      <div className="flex flex-col gap-3">
        {sorted?.map((e) => (
          <EdgeRow key={`${e.caller}->${e.callee}`} e={e} />
        ))}
      </div>
    </>
  );
}