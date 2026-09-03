"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Incident, Bottleneck, GraphEdge, ApiError } from "@/lib/api";
import { IncidentHero } from "@/components/IncidentHero";

const SEVERITY_COLOR: Record<Incident["severity"], string> = {
  critical: "text-status-red",
  high: "text-status-red",
  medium: "text-status-amber",
  low: "text-status-green",
};

const SEVERITY_RANK: Record<Incident["severity"], number> = { critical: 4, high: 3, medium: 2, low: 1 };

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function BottleneckPreviewRow({ b, rank }: { b: Bottleneck; rank: number }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setWidth(Math.round(b.risk_score * 100)));
    return () => cancelAnimationFrame(id);
  }, [b.risk_score]);

  return (
    <div className="px-4 py-2.5 border-b border-[#1b1a17] last:border-0">
      <div className="flex justify-between">
        <span className="text-[#d4cec2]">
          {String(rank).padStart(2, "0")} · {b.service}
        </span>
        <span className="text-[#b1aa9d]">{Math.round(b.risk_score * 100)}</span>
      </div>
      <div className="h-[3px] bg-[#1b1a17] mt-2 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-[width] duration-700 ease-out ${
            b.risk_score > 0.75 ? "bg-status-red" : b.risk_score > 0.5 ? "bg-status-amber" : "bg-[#9f8b45]"
          }`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [bottlenecks, setBottlenecks] = useState<Bottleneck[] | null>(null);
  const [graph, setGraph] = useState<GraphEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.incidents(), api.bottlenecks(), api.graph()])
      .then(([inc, bn, gr]) => {
        setIncidents(inc);
        setBottlenecks(bn);
        setGraph(gr);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load overview data"));
  }, []);

  const loading = incidents === null || bottlenecks === null || graph === null;

  const servicesObserved = graph ? new Set(graph.flatMap((e) => [e.caller, e.callee])).size : null;
  const openIncidents = incidents ? incidents.filter((i) => i.status === "open" || i.status === "diagnosing") : [];
  const criticalCount = openIncidents.filter((i) => i.severity === "critical").length;

  const worstIncident = openIncidents.length
    ? [...openIncidents].sort((a, b) => {
        const rankDiff = SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity];
        if (rankDiff !== 0) return rankDiff;
        return new Date(a.started_at).getTime() - new Date(b.started_at).getTime();
      })[0]
    : null;

  return (
    <>
      <div className="flex justify-between items-end mt-1 mb-6">
        <div>
          <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em] flex items-center gap-2">
            Behavioral observability
            <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
          </div>
          <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">System overview</h1>
          <div className="text-ghost-muted mt-2">A living view of how your production system behaves.</div>
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      {!loading && <IncidentHero incident={worstIncident} openCount={openIncidents.length} />}

      <section className="grid grid-cols-3 border border-border bg-surface rounded-md overflow-hidden mb-3">
        <div className="p-4 border-r border-border">
          <div className="font-display text-[22px] font-semibold text-status-green">
            {loading ? "—" : servicesObserved}
          </div>
          <div className="text-ghost-muted text-[9px] uppercase tracking-[0.1em] mt-1.5">services observed</div>
        </div>
        <div className="p-4 border-r border-border">
          <div className="font-display text-[22px] font-semibold text-status-red">
            {loading ? "—" : openIncidents.length}
          </div>
          <div className="text-ghost-muted text-[9px] uppercase tracking-[0.1em] mt-1.5">open incidents</div>
        </div>
        <div className="p-4">
          <div className="font-display text-[22px] font-semibold text-status-amber">
            {loading ? "—" : criticalCount}
          </div>
          <div className="text-ghost-muted text-[9px] uppercase tracking-[0.1em] mt-1.5">critical</div>
        </div>
      </section>

      <section className="grid grid-cols-[minmax(0,1fr)_310px] gap-3 mt-3">
        <div className="relative bg-surface border border-border rounded-md overflow-hidden">
          <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-60 z-10" />
          <div className="h-[43px] px-4 border-b border-border flex items-center justify-between">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Active incidents</h2>
            <span className="text-[9px] text-ghost-muted">{loading ? "..." : `${openIncidents.length} active`}</span>
          </div>
          {loading && <div className="p-4 text-ghost-dim text-xs">Loading...</div>}
          {!loading && openIncidents.length === 0 && (
            <div className="p-4 text-ghost-dim text-xs">No open incidents -- all quiet.</div>
          )}
          {openIncidents.map((inc) => {
            const hot = inc.severity === "critical" || inc.severity === "high";
            return (
              <Link
                key={inc.id}
                href={`/incidents/${inc.id}`}
                className="block px-4 py-3.5 border-b border-[#1b1a17] last:border-0 hover:bg-surface-hi transition-colors"
              >
                <div className="flex items-center gap-2">
                  {hot ? (
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
                    </span>
                  ) : (
                    <span className={`w-1.5 h-1.5 rounded-full ${inc.severity === "medium" ? "bg-status-amber" : "bg-status-green"}`} />
                  )}
                  <span className="text-[#ddd7cc]">{inc.title}</span>
                  <span className={`ml-auto text-[8px] uppercase tracking-[0.08em] ${SEVERITY_COLOR[inc.severity]}`}>
                    {inc.severity}
                  </span>
                </div>
                <div className="flex justify-between mt-2.5 ml-3.5 text-ghost-muted text-[9px]">
                  <span>{inc.primary_service}</span>
                  <span>{timeAgo(inc.last_seen_at)}</span>
                </div>
              </Link>
            );
          })}
        </div>

        <div className="relative bg-surface border border-border rounded-md overflow-hidden">
          <span className="pointer-events-none absolute top-2 right-2 w-4 h-4 border-t border-r border-hud-bright opacity-60 z-10" />
          <div className="h-[43px] px-4 border-b border-border flex items-center justify-between">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Top bottlenecks</h2>
            <span className="text-[9px] text-ghost-muted">risk score</span>
          </div>
          {loading && <div className="p-4 text-ghost-dim text-xs">Loading...</div>}
          {!loading && bottlenecks && bottlenecks.length === 0 && (
            <div className="p-4 text-ghost-dim text-xs">Not enough graph data yet.</div>
          )}
          {bottlenecks?.slice(0, 5).map((b, i) => (
            <BottleneckPreviewRow key={b.service} b={b} rank={i + 1} />
          ))}
        </div>
      </section>
    </>
  );
}