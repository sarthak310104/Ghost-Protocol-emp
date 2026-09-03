"use client";

import { useEffect, useState } from "react";
import { Bottleneck } from "@/lib/api";

function riskColor(score: number): string {
  if (score > 0.75) return "#c94a3a";
  if (score > 0.5) return "#d4a13d";
  return "#55bd78";
}

/**
 * The single hero moment on this page -- everything else is a compact
 * list row, this is a full instrument dial, on purpose. A filled bar
 * or a bigger number in a bigger box reads as "the same thing, scaled
 * up." A genuinely different visual object -- tick-marked ring,
 * continuously rotating orbit sweep, animated fill -- reads as "this
 * one actually matters," which is the point: there's exactly one #1.
 */
export function BottleneckGauge({ b }: { b: Bottleneck }) {
  const [pct, setPct] = useState(0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setPct(Math.round(b.risk_score * 100)));
    return () => cancelAnimationFrame(id);
  }, [b.risk_score]);

  const color = riskColor(b.risk_score);

  return (
    <div className="relative bg-surface border border-hud-bright/40 rounded-md p-6 mb-6 overflow-hidden">
      <span className="pointer-events-none absolute top-3 left-3 w-5 h-5 border-t border-l border-hud-bright opacity-70" />
      <span className="pointer-events-none absolute bottom-3 right-3 w-5 h-5 border-b border-r border-hud-bright opacity-70" />

      <div className="flex items-center gap-8">
        <div className="relative w-[140px] h-[140px] flex-shrink-0 flex items-center justify-center">
          {/* tick-mark ring */}
          <div
            className="absolute inset-[-10px] rounded-full opacity-60"
            style={{
              background: "repeating-conic-gradient(from 0deg, #5f7a7a 0deg 1.2deg, transparent 1.2deg 9deg)",
              WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
              mask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
            }}
          />
          {/* rotating orbit sweep */}
          <div
            className="absolute inset-0 rounded-full"
            style={{
              border: `1px solid transparent`,
              borderTopColor: color,
              animation: "gaugeOrbit 4s linear infinite",
            }}
          />
          {/* base ring + inner rings, matches the signal-core concept */}
          <div className="absolute inset-0 rounded-full border border-[#2b2b2b]" />
          <div className="absolute inset-3 rounded-full border border-[#25241f]" />

          <div className="flex flex-col items-center">
            <span className="font-display text-[34px] font-semibold" style={{ color }}>
              {pct}
            </span>
            <span className="text-ghost-dim text-[8px] uppercase tracking-[0.14em] mt-1">risk score</span>
          </div>
        </div>

        <div className="flex-1">
          <div className="text-ghost-dim text-[9px] uppercase tracking-[0.13em]">Top structural risk</div>
          <div className="text-ghost-text text-[20px] font-display font-semibold mt-1">{b.service}</div>
          <div className="text-[11px] mt-1">
            {b.has_reference_baseline && b.risk_zscore !== null ? (
              <span className={Math.abs(b.risk_zscore) > 3 ? "text-status-red" : "text-ghost-dim"}>
                {Math.abs(b.risk_zscore).toFixed(1)}σ {b.risk_zscore > 0 ? "above" : "below"} its own normal
              </span>
            ) : (
              <span className="text-ghost-dim">no baseline established yet for this service</span>
            )}
          </div>

          <div className="grid grid-cols-4 gap-4 mt-5">
            <div>
              <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-in</div>
              <div className="text-ghost-text text-[15px] mt-1">{b.fan_in}</div>
            </div>
            <div>
              <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Fan-out</div>
              <div className="text-ghost-text text-[15px] mt-1">{b.fan_out}</div>
            </div>
            <div>
              <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Critical path</div>
              <div className="text-ghost-text text-[15px] mt-1">{Math.round(b.critical_path_membership * 100)}%</div>
            </div>
            <div>
              <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Error rate</div>
              <div className="text-ghost-text text-[15px] mt-1">{(b.error_rate_baseline * 100).toFixed(1)}%</div>
            </div>
          </div>

          {b.contributing_edges.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {b.contributing_edges.map((edge) => (
                <span key={edge} className="text-[11px] text-[#b8b1a5] border border-border rounded px-2 py-1">
                  {edge}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <style jsx>{`
        @keyframes gaugeOrbit {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </div>
  );
}