"use client";

import { useEffect, useState } from "react";
import { api, ServiceReliabilityTrend, WeeklyReliabilityBucket, ApiError } from "@/lib/api";

function weekLabel(b: WeeklyReliabilityBucket): string {
  return b.weeks_ago === 0 ? "now" : `-${b.weeks_ago}w`;
}

function fmtDuration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 90) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

// Bucket height color follows severity mix, not just count -- a week
// with one critical incident should read differently from a week with
// three low-severity ones, even if the bar heights end up similar.
function incidentBarColor(b: WeeklyReliabilityBucket): string {
  if (b.incident_count === 0) return "bg-[#242320]";
  if (b.severity_counts.critical) return "bg-status-red";
  if (b.severity_counts.high) return "bg-status-amber";
  return "bg-[#9f8b45]";
}

function ServiceTrendPanel({ trend }: { trend: ServiceReliabilityTrend }) {
  const maxIncidents = Math.max(1, ...trend.weeks.map((w) => w.incident_count));
  const maxMttr = Math.max(1, ...trend.weeks.map((w) => w.mttr_mean_seconds ?? 0));
  const totalIncidents = trend.weeks.reduce((sum, w) => sum + w.incident_count, 0);

  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <div className="h-[38px] px-4 border-b border-border flex items-center">
        <h2 className="text-[12px] text-ghost-text">{trend.service_name}</h2>
        <span className="ml-auto text-ghost-dim text-[10px]">
          {totalIncidents} incident{totalIncidents === 1 ? "" : "s"} over {trend.weeks.length}w
        </span>
      </div>

      <div className="p-4">
        <div className="text-ghost-dim text-[9px] uppercase tracking-wide mb-2">Incidents / week</div>
        <div className="flex items-end gap-1.5 h-[64px]">
          {trend.weeks.map((w) => (
            <div key={w.weeks_ago} className="flex-1 flex flex-col items-center justify-end h-full gap-1">
              <div
                title={`${w.incident_count} incident${w.incident_count === 1 ? "" : "s"}, week starting ${new Date(w.bucket_start).toLocaleDateString()}`}
                className={`w-full rounded-sm transition-[height] duration-500 ease-out ${incidentBarColor(w)}`}
                style={{ height: `${Math.max(3, (w.incident_count / maxIncidents) * 100)}%` }}
              />
            </div>
          ))}
        </div>
        <div className="flex gap-1.5 mt-1">
          {trend.weeks.map((w) => (
            <div key={w.weeks_ago} className="flex-1 text-center text-ghost-dim text-[8px]">
              {weekLabel(w)}
            </div>
          ))}
        </div>

        <div className="text-ghost-dim text-[9px] uppercase tracking-wide mt-4 mb-2">Mean time to resolve / week</div>
        <div className="flex items-end gap-1.5 h-[40px]">
          {trend.weeks.map((w) => (
            <div key={w.weeks_ago} className="flex-1 flex flex-col items-center justify-end h-full gap-1">
              {w.mttr_mean_seconds !== null ? (
                <div
                  title={`mean ${fmtDuration(w.mttr_mean_seconds)} · median ${fmtDuration(w.mttr_median_seconds ?? 0)} · ${w.resolved_count} resolved`}
                  className="w-full rounded-sm bg-[#9fc0c0] transition-[height] duration-500 ease-out"
                  style={{ height: `${Math.max(3, (w.mttr_mean_seconds / maxMttr) * 100)}%` }}
                />
              ) : (
                <div className="w-full rounded-sm bg-[#242320]" style={{ height: "3%" }} />
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function TrendsPage() {
  const [trends, setTrends] = useState<ServiceReliabilityTrend[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .reliabilityTrends(12)
      .then(setTrends)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load reliability trends"));
  }, []);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Understand</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Trends</h1>
        <div className="text-ghost-muted mt-2">
          Per-service incident frequency and mean time to resolve, over the last 12 weeks --
          not an uptime percentage. Ghost only retains Incident history long-term; raw spans
          and metrics age out after a short retention window, so there's no continuous health
          signal to derive a precise uptime figure from without overclaiming.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      {trends === null && !error && <div className="text-ghost-dim text-xs">Loading...</div>}

      {trends !== null && trends.length === 0 && (
        <div className="bg-surface border border-border rounded-md p-4 text-ghost-dim text-xs">
          No incidents recorded in the last 12 weeks -- nothing to trend yet.
        </div>
      )}

      <div className="flex flex-col gap-4">
        {trends?.map((t) => (
          <ServiceTrendPanel key={t.service_name} trend={t} />
        ))}
      </div>
    </>
  );
}