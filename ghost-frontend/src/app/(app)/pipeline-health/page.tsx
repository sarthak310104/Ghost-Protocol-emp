"use client";

import { useEffect, useState } from "react";
import { api, ApiError, PipelineHealth } from "@/lib/api";

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

const KIND_LABEL: Record<string, string> = {
  anomaly_scan: "Anomaly scan",
  bottleneck_scan: "Bottleneck scan",
};

export default function PipelineHealthPage() {
  const [health, setHealth] = useState<PipelineHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .pipelineHealth()
      .then(setHealth)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load pipeline health"));
  }, []);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">This workspace only</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Pipeline Health</h1>
        <div className="text-ghost-muted mt-2">
          Is Ghost actually watching your data right now -- not infrastructure metrics across every
          workspace, just whether your own pipeline is current.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {health === null && !error && <div className="text-ghost-dim text-xs">Loading...</div>}

      {health && (
        <>
          <div className="relative bg-surface border border-hud-bright/40 rounded-md p-5 mb-6 overflow-hidden">
            <span className="pointer-events-none absolute top-3 left-3 w-5 h-5 border-t border-l border-hud-bright opacity-70" />
            <span className="pointer-events-none absolute bottom-3 right-3 w-5 h-5 border-b border-r border-hud-bright opacity-70" />

            <div className="flex items-center gap-2 text-ghost-dim text-[9px] uppercase tracking-[0.13em] mb-4">
              Freshness
              <span className={`w-1 h-1 rounded-full ${health.is_stale ? "bg-status-red" : "bg-status-green animate-pulse"}`} />
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div>
                <div className={`font-display text-[22px] font-semibold ${health.is_stale ? "text-status-red" : "text-status-green"}`}>
                  {timeAgo(health.last_data_received_at)}
                </div>
                <div className="text-ghost-muted text-[9px] uppercase tracking-wide mt-1">last data received</div>
              </div>
              <div>
                <div className="font-display text-[22px] font-semibold text-ghost-text">
                  {timeAgo(health.last_scan_at)}
                </div>
                <div className="text-ghost-muted text-[9px] uppercase tracking-wide mt-1">last successful scan</div>
              </div>
            </div>

            {health.is_stale && (
              <div className="text-status-red text-[11px] mt-4 pt-3 border-t border-[#1b1a17]">
                No data in the last 15 minutes -- check that traffic is actually being sent to this workspace.
              </div>
            )}
          </div>

          <div className="bg-surface border border-border rounded-md overflow-hidden">
            <div className="h-[43px] px-4 border-b border-border flex items-center">
              <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Recent activity</h2>
            </div>

            {health.recent_events.length === 0 && (
              <div className="p-4 text-ghost-dim text-xs">No pipeline activity recorded yet for this workspace.</div>
            )}

            <div className="p-4 flex flex-col gap-0">
              {health.recent_events.map((e, i) => (
                <div key={i} className="flex gap-4 text-[12px] relative pb-4 last:pb-0">
                  {i < health.recent_events.length - 1 && (
                    <span className="absolute left-[3px] top-3 bottom-0 w-px bg-[#2b2b2b]" />
                  )}
                  <span className={`h-1.5 w-1.5 mt-1 flex-shrink-0 rounded-full ${e.is_error ? "bg-status-red" : "bg-status-green"}`} />
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="text-ghost-text">{KIND_LABEL[e.kind] ?? e.kind}</span>
                      {e.is_error && <span className="text-status-red text-[8px] uppercase tracking-wide">failed</span>}
                      <span className="ml-auto text-ghost-dim text-[10px]">{fmtTime(e.occurred_at)}</span>
                    </div>
                    {e.detail && (
                      <div className={`text-[11px] mt-1 ${e.is_error ? "text-status-red" : "text-ghost-muted"}`}>
                        {e.detail}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}