"use client";

import Link from "next/link";
import { Incident } from "@/lib/api";

function severityColor(sev: Incident["severity"]): string {
  if (sev === "critical" || sev === "high") return "#c94a3a";
  if (sev === "medium") return "#d4a13d";
  return "#55bd78";
}

function elapsed(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

/**
 * Unlike the bottleneck gauge, this never fabricates a numeric score in
 * the dial's center -- incidents don't have one. Elapsed time since it
 * started is the real, honest number worth putting there: it's
 * meaningful (a longer-running incident is more concerning) and it's
 * actually true, not a manufactured percentage standing in for
 * severity.
 */
export function IncidentHero({ incident, openCount }: { incident: Incident | null; openCount: number }) {
  if (!incident) {
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
            <div className="absolute inset-0 rounded-full border border-[#2b2b2b]" />
            <div className="absolute inset-3 rounded-full border border-[#25241f]" />
            <div className="flex flex-col items-center">
              <span className="text-status-green text-[28px]">✓</span>
              <span className="text-ghost-dim text-[8px] uppercase tracking-[0.14em] mt-1">all clear</span>
            </div>
          </div>
          <div>
            <div className="text-ghost-dim text-[9px] uppercase tracking-[0.13em]">System status</div>
            <div className="text-ghost-text text-[20px] font-display font-semibold mt-1">
              No open incidents
            </div>
            <div className="text-ghost-muted text-[12px] mt-2">Ghost is watching -- nothing needs attention right now.</div>
          </div>
        </div>
      </div>
    );
  }

  const color = severityColor(incident.severity);

  return (
    <Link
      href={`/incidents/${incident.id}`}
      className="relative block bg-surface border border-hud-bright/40 rounded-md p-6 mb-6 overflow-hidden hover:border-hud-bright/70 transition-colors"
    >
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
          <div
            className="absolute inset-0 rounded-full"
            style={{ border: "1px solid transparent", borderTopColor: color, animation: "heroOrbit 4s linear infinite" }}
          />
          <div className="absolute inset-0 rounded-full border border-[#2b2b2b]" />
          <div className="absolute inset-3 rounded-full border border-[#25241f]" />
          <div className="flex flex-col items-center">
            <span className="font-display text-[30px] font-semibold" style={{ color }}>
              {elapsed(incident.started_at)}
            </span>
            <span className="text-ghost-dim text-[8px] uppercase tracking-[0.14em] mt-1">ongoing</span>
          </div>
        </div>

        <div className="flex-1">
          <div className="flex items-center gap-2 text-ghost-dim text-[9px] uppercase tracking-[0.13em]">
            Most urgent open incident
            {openCount > 1 && <span>· {openCount - 1} other{openCount > 2 ? "s" : ""} open</span>}
          </div>
          <div className="text-ghost-text text-[20px] font-display font-semibold mt-1">{incident.title}</div>
          <div className="flex items-center gap-3 mt-3">
            <span
              className="px-2 py-0.5 rounded border text-[10px] uppercase tracking-wide"
              style={{ color, borderColor: color + "55" }}
            >
              {incident.severity}
            </span>
            <span className="text-ghost-muted text-[12px]">{incident.primary_service}</span>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes heroOrbit {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </Link>
  );
}