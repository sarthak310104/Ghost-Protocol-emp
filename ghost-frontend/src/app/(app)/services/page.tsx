"use client";

import { useEffect, useState } from "react";
import { api, ApiError, ServiceSummary } from "@/lib/api";

function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function isStale(iso: string): boolean {
  return Date.now() - new Date(iso).getTime() > 15 * 60 * 1000; // 15 min, same order as this app's own scan cadence
}

function riskColor(score: number): string {
  if (score > 0.75) return "text-status-red";
  if (score > 0.5) return "text-status-amber";
  return "text-status-green";
}

function ServiceRow({ s }: { s: ServiceSummary }) {
  const stale = isStale(s.last_seen_at);
  const hot = s.has_reference_baseline && s.risk_zscore !== null && Math.abs(s.risk_zscore) > 3;

  return (
    <div className="bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        <span className={`w-1.5 h-1.5 rounded-full ${stale ? "bg-ghost-dim" : "bg-status-green"}`} />
        <span className="text-ghost-text text-[14px]">{s.name}</span>
        {hot && (
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
          </span>
        )}
        <span className={`ml-auto font-display text-[16px] font-semibold ${riskColor(s.current_risk_score)}`}>
          {Math.round(s.current_risk_score * 100)}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-4 mt-4">
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-in</div>
          <div className="text-ghost-text text-[13px] mt-1">{s.fan_in}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-out</div>
          <div className="text-ghost-text text-[13px] mt-1">{s.fan_out}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">First seen</div>
          <div className="text-ghost-text text-[13px] mt-1">{timeAgo(s.first_seen_at)}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Last seen</div>
          <div className={`text-[13px] mt-1 ${stale ? "text-ghost-dim" : "text-ghost-text"}`}>
            {timeAgo(s.last_seen_at)}
          </div>
        </div>
      </div>

      <div className="mt-2">
        {s.has_reference_baseline && s.risk_zscore !== null ? (
          <span className={`text-[10px] ${hot ? "text-status-red" : "text-ghost-dim"}`}>
            {Math.abs(s.risk_zscore).toFixed(1)}σ {s.risk_zscore > 0 ? "above" : "below"} its own normal
          </span>
        ) : (
          <span className="text-ghost-dim text-[10px]">no baseline yet</span>
        )}
      </div>
    </div>
  );
}

export default function ServicesPage() {
  const [services, setServices] = useState<ServiceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .services()
      .then(setServices)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load services"));
  }, []);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Discovered automatically</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Services</h1>
        <div className="text-ghost-muted mt-2">
          Every service Ghost has ever seen in this workspace, including ones that have gone quiet --
          nothing here was manually registered.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {services === null && <div className="text-ghost-dim text-xs">Loading...</div>}
      {services !== null && services.length === 0 && (
        <div className="text-ghost-dim text-xs">No services discovered yet -- send some traffic first.</div>
      )}

      <div className="flex flex-col gap-3">
        {services?.map((s) => (
          <ServiceRow key={s.name} s={s} />
        ))}
      </div>
    </>
  );
}