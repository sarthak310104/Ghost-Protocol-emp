"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Incident, ApiError } from "@/lib/api";

const SEVERITY_COLOR: Record<Incident["severity"], string> = {
  critical: "text-status-red",
  high: "text-status-red",
  medium: "text-status-amber",
  low: "text-status-green",
};

const SEVERITY_DOT: Record<Incident["severity"], string> = {
  critical: "bg-status-red",
  high: "bg-status-red",
  medium: "bg-status-amber",
  low: "bg-status-green",
};

const STATUS_FILTERS: { label: string; value: string | undefined }[] = [
  { label: "All", value: undefined },
  { label: "Open", value: "open" },
  { label: "Diagnosing", value: "diagnosing" },
  { label: "Resolved", value: "resolved" },
  { label: "Dismissed", value: "dismissed" },
];

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIncidents(null);
    api
      .incidents(filter)
      .then(setIncidents)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load incidents"));
  }, [filter]);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em] flex items-center gap-2">
          Behavioral observability
          <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
        </div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Incidents</h1>
        <div className="text-ghost-muted mt-2">Every anomaly Ghost has detected, correlated, and evidenced.</div>
      </div>

      <div className="flex gap-2 mb-4">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            className={`text-[10px] uppercase tracking-[0.08em] px-3 py-1.5 rounded border transition-colors
              ${filter === f.value ? "border-hud-bright text-ghost-text bg-surface-hi" : "border-border text-ghost-muted hover:text-ghost-text"}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      <div className="relative bg-surface border border-border rounded-md overflow-hidden">
        <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-60 z-10" />
        <span className="pointer-events-none absolute bottom-2 right-2 w-4 h-4 border-b border-r border-hud-bright opacity-60 z-10" />
        {incidents === null && <div className="p-4 text-ghost-dim text-xs">Loading...</div>}
        {incidents !== null && incidents.length === 0 && (
          <div className="p-4 text-ghost-dim text-xs">No incidents match this filter.</div>
        )}
        {incidents?.map((inc) => {
          const hot = (inc.status === "open" || inc.status === "diagnosing") && (inc.severity === "critical" || inc.severity === "high");
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
                  <span className={`w-1.5 h-1.5 rounded-full ${SEVERITY_DOT[inc.severity]}`} />
                )}
                <span className="text-[#ddd7cc]">{inc.title}</span>
                <span className={`ml-auto text-[8px] uppercase tracking-[0.08em] ${SEVERITY_COLOR[inc.severity]}`}>
                  {inc.severity}
                </span>
                <span className="text-[8px] uppercase tracking-[0.08em] text-ghost-dim border border-border rounded px-1.5 py-0.5">
                  {inc.status}
                </span>
              </div>
              <div className="flex justify-between mt-2.5 ml-3.5 text-ghost-muted text-[9px]">
                <span>{inc.primary_service}</span>
                <span>
                  {inc.status === "resolved" && inc.resolved_at
                    ? `resolved ${timeAgo(inc.resolved_at)}`
                    : `last seen ${timeAgo(inc.last_seen_at)}`}
                </span>
              </div>
            </Link>
          );
        })}
      </div>
    </>
  );
}