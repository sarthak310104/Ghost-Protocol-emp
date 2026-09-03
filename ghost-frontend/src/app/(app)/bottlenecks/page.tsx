"use client";

import { useEffect, useState } from "react";
import { api, Bottleneck, ApiError } from "@/lib/api";
import { BottleneckGauge } from "@/components/BottleneckGauge";

// A service only counts as "hot" relative to ITS OWN history -- not a
// fixed cutoff applied uniformly to every service. 3 standard
// deviations matches ANOMALY_ZSCORE_THRESHOLD, the same convention the
// incident detector already uses elsewhere in this platform. A service
// with no reference baseline yet (has_reference_baseline: false) is
// never treated as hot -- there's nothing established to deviate from.
function isHot(b: Bottleneck): boolean {
  return b.has_reference_baseline && b.risk_zscore !== null && Math.abs(b.risk_zscore) > 3;
}

function riskColor(score: number): string {
  if (score > 0.75) return "text-status-red";
  if (score > 0.5) return "text-status-amber";
  return "text-status-green";
}

function riskBarColor(score: number): string {
  if (score > 0.75) return "bg-status-red";
  if (score > 0.5) return "bg-status-amber";
  return "bg-[#9f8b45]";
}

function DeviationNote({ b }: { b: Bottleneck }) {
  if (!b.has_reference_baseline) {
    return <span className="text-ghost-dim text-[10px]">no baseline yet</span>;
  }
  if (b.risk_zscore === null) return null;
  const direction = b.risk_zscore > 0 ? "above" : "below";
  return (
    <span className={`text-[10px] ${isHot(b) ? "text-status-red" : "text-ghost-dim"}`}>
      {Math.abs(b.risk_zscore).toFixed(1)}σ {direction} its own normal
    </span>
  );
}

function BottleneckRow({ b, rank }: { b: Bottleneck; rank: number }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setWidth(Math.round(b.risk_score * 100)));
    return () => cancelAnimationFrame(id);
  }, [b.risk_score]);

  const hot = isHot(b);

  return (
    <div className="bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        <span className="text-ghost-dim text-[11px] w-6">{String(rank).padStart(2, "0")}</span>
        <span className="text-ghost-text text-[14px]">{b.service}</span>
        {hot && (
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-status-red" />
          </span>
        )}
        <span className={`ml-auto font-display text-[18px] font-semibold ${riskColor(b.risk_score)}`}>
          {Math.round(b.risk_score * 100)}
        </span>
      </div>

      <div className="h-[3px] bg-[#1b1a17] mt-3 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-[width] duration-700 ease-out ${riskBarColor(b.risk_score)}`}
          style={{ width: `${width}%`, boxShadow: hot ? "0 0 8px rgba(201,74,58,0.6)" : undefined }}
        />
      </div>

      <div className="mt-2">
        <DeviationNote b={b} />
      </div>

      <div className="grid grid-cols-4 gap-4 mt-3">
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-in</div>
          <div className="text-ghost-text text-[13px] mt-1">{b.fan_in}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-out</div>
          <div className="text-ghost-text text-[13px] mt-1">{b.fan_out}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Critical path</div>
          <div className="text-ghost-text text-[13px] mt-1">{Math.round(b.critical_path_membership * 100)}%</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Error rate</div>
          <div className="text-ghost-text text-[13px] mt-1">{(b.error_rate_baseline * 100).toFixed(1)}%</div>
        </div>
      </div>

      {b.contributing_edges.length > 0 && (
        <div className="mt-4 pt-3 border-t border-[#1b1a17]">
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide mb-2">Contributing edges</div>
          <div className="flex flex-wrap gap-2">
            {b.contributing_edges.map((edge) => (
              <span key={edge} className="text-[11px] text-[#b8b1a5] border border-border rounded px-2 py-1">
                {edge}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="bg-surface border border-border rounded-md p-4 animate-pulse"
          style={{ animationDelay: `${i * 120}ms` }}
        >
          <div className="flex items-center gap-3">
            <div className="h-3 w-6 bg-[#1b1a17] rounded" />
            <div className="h-3 w-28 bg-[#1b1a17] rounded" />
            <div className="ml-auto h-4 w-8 bg-[#1b1a17] rounded" />
          </div>
          <div className="h-[3px] bg-[#1b1a17] mt-3 rounded-full" />
        </div>
      ))}
    </div>
  );
}

export default function BottlenecksPage() {
  const [bottlenecks, setBottlenecks] = useState<Bottleneck[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .bottlenecks()
      .then(setBottlenecks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load bottlenecks"));
  }, []);

  const [top, ...rest] = bottlenecks ?? [];

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em] flex items-center gap-2">
          Structural risk
          <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
        </div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Bottlenecks</h1>
        <div className="text-ghost-muted mt-2">
          Services that are structurally risky right now -- high fan-in, sitting on critical paths, or
          already showing elevated error rates -- independent of whether an incident is currently open.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      {bottlenecks === null && <LoadingSkeleton />}
      {bottlenecks !== null && bottlenecks.length === 0 && (
        <div className="text-ghost-dim text-xs">Not enough graph data yet to compute structural risk.</div>
      )}

      {top && <BottleneckGauge b={top} />}

      <div className="flex flex-col gap-3">
        {rest.map((b, i) => (
          <BottleneckRow key={b.service} b={b} rank={i + 2} />
        ))}
      </div>
    </>
  );
}