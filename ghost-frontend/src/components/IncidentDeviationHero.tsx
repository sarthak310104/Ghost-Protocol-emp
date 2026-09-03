"use client";

import { Observation } from "@/lib/api";

function severityFromPct(pct: number): { color: string; label: string } {
  if (pct > 100) return { color: "#c94a3a", label: "critical deviation" };
  if (pct > 30) return { color: "#d4a13d", label: "elevated" };
  return { color: "#55bd78", label: "within range" };
}

export function IncidentDeviationHero({ primary, active }: { primary: Observation | null; active: boolean }) {
  if (!primary || primary.baseline === undefined || primary.baseline <= 0) {
    return null; // nothing honest to show a gauge for without a real baseline to compare against
  }

  const pct = Math.round(((primary.current - primary.baseline) / primary.baseline) * 100);
  const { color, label } = severityFromPct(pct);

  return (
    <div className="relative bg-surface border border-hud-bright/40 rounded-md p-6 mb-6 overflow-hidden">
      <span className="pointer-events-none absolute top-3 left-3 w-5 h-5 border-t border-l border-hud-bright opacity-70" />
      <span className="pointer-events-none absolute bottom-3 right-3 w-5 h-5 border-b border-r border-hud-bright opacity-70" />

      <div className="flex items-center gap-8">
        <div className="relative w-[140px] h-[140px] flex-shrink-0 flex items-center justify-center">
          <div
            className="absolute inset-[-10px] rounded-full opacity-60"
            style={{
              background: "repeating-conic-gradient(from 0deg, #5f7a7a 0deg 1.2deg, transparent 1.2deg 9deg)",
              WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
              mask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
            }}
          />
          {active && (
            <div
              className="absolute inset-0 rounded-full"
              style={{ border: "1px solid transparent", borderTopColor: color, animation: "devOrbit 4s linear infinite" }}
            />
          )}
          <div className="absolute inset-0 rounded-full border border-[#2b2b2b]" />
          <div className="absolute inset-3 rounded-full border border-[#25241f]" />
          <div className="flex flex-col items-center">
            <span className="font-display text-[28px] font-semibold" style={{ color }}>
              {pct > 0 ? "+" : ""}{pct}%
            </span>
            <span className="text-ghost-dim text-[8px] uppercase tracking-[0.14em] mt-1">vs normal</span>
          </div>
        </div>

        <div className="flex-1">
          <div className="text-ghost-dim text-[9px] uppercase tracking-[0.13em]">{primary.metric}</div>
          <div className="text-[20px] font-display font-semibold mt-1" style={{ color }}>
            {label}
          </div>
          <div className="flex items-center gap-4 mt-3 text-[12px]">
            <span className="text-ghost-muted">current <span className="text-ghost-text">{primary.current}</span></span>
            <span className="text-ghost-muted">baseline <span className="text-ghost-text">{primary.baseline}</span></span>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes devOrbit {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </div>
  );
}