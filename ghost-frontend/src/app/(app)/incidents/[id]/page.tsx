"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, EvidencePackage, Incident, ApiError } from "@/lib/api";
import { IncidentDeviationHero } from "@/components/IncidentDeviationHero";

const SEVERITY_BADGE: Record<Incident["severity"], string> = {
  critical: "text-status-red border-[#3a1712] bg-gradient-to-b from-[#170e0b] to-[#120a08]",
  high: "text-status-red border-[#3a1712] bg-gradient-to-b from-[#170e0b] to-[#120a08]",
  medium: "text-status-amber border-border bg-surface",
  low: "text-status-green border-border bg-surface",
};

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtPct(n: number): string {
  return `${n > 0 ? "+" : ""}${n}%`;
}

export default function IncidentDetailPage() {
  const params = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [evidence, setEvidence] = useState<EvidencePackage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  useEffect(() => {
    // The evidence endpoint doesn't return status/started_at/severity
    // (it's evidence, not the incident record itself), so the header
    // needs a separate call to the plain incidents list, matched by id.
    // A dedicated GET /v1/incidents/{id} exists on the backend for
    // exactly this, but returns a differently-shaped payload (raw
    // `evidence` + `reasoning_results`, not the assembled package) --
    // simplest correct approach here is finding this incident from the
    // list rather than reconciling two different response shapes.
    api.incidents().then((all) => {
      const found = all.find((i) => i.id === params.id);
      if (found) setIncident(found);
    }).catch(() => {});

    api
      .incidentEvidence(params.id)
      .then(setEvidence)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load evidence"));
  }, [params.id]);

  async function handleResolve() {
    setResolving(true);
    try {
      await api.resolveIncident(params.id);
      setIncident((prev) => (prev ? { ...prev, status: "resolved", resolved_at: new Date().toISOString() } : prev));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to resolve incident");
    } finally {
      setResolving(false);
    }
  }

  if (error) return <div className="text-status-red text-xs mt-4">{error}</div>;
  if (!evidence) return <div className="text-ghost-dim text-xs mt-4">Loading...</div>;

  const sim = evidence.simulation_results[evidence.simulation_results.length - 1];

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">INC-{evidence.incident.id.slice(0, 8)}</div>
        <h1 className="font-display text-[22px] font-semibold tracking-tight mt-2">
          {incident?.title ?? evidence.incident.service}
        </h1>
        <div className="flex items-center gap-3 mt-3 text-[11px] text-ghost-muted">
          {incident && (
            <span className={`px-2 py-0.5 rounded border text-[10px] uppercase tracking-wide ${SEVERITY_BADGE[incident.severity]}`}>
              {incident.severity}
            </span>
          )}
          {incident && <span>started {fmtTime(incident.started_at)}</span>}
          {incident?.status === "resolved" ? (
            <span className="text-status-green">● resolved{incident.resolved_at ? ` ${fmtTime(incident.resolved_at)}` : ""}</span>
          ) : (
            <span className="text-status-green flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-green opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-green" />
              </span>
              still active
            </span>
          )}
          {incident && incident.status !== "resolved" && (
            <button
              onClick={handleResolve}
              disabled={resolving}
              className="ml-auto text-[10px] uppercase tracking-wide border border-border rounded px-3 py-1
                         text-ghost-muted hover:text-ghost-text hover:border-status-green transition-colors disabled:opacity-40"
            >
              {resolving ? "Resolving..." : "Mark resolved"}
            </button>
          )}
        </div>
      </div>

      <IncidentDeviationHero
        primary={evidence.observations[0] ?? null}
        active={incident?.status !== "resolved"}
      />

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-surface border border-border rounded-md overflow-hidden">
          <div className="h-[38px] px-4 border-b border-border flex items-center">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Observations</h2>
          </div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-ghost-dim text-[9px] uppercase tracking-wide">
                <th className="text-left font-normal px-4 py-2">Metric</th>
                <th className="text-right font-normal px-4 py-2">Current</th>
                <th className="text-right font-normal px-4 py-2">Baseline</th>
              </tr>
            </thead>
            <tbody>
              {evidence.observations.map((o, i) => (
                <tr key={i} className="border-t border-[#1b1a17]">
                  <td className="px-4 py-2 text-[#d4cec2]">{o.metric}</td>
                  <td className="px-4 py-2 text-right text-ghost-text">{o.current}</td>
                  <td className="px-4 py-2 text-right text-ghost-muted">{o.baseline ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-surface border border-border rounded-md overflow-hidden">
          <div className="h-[38px] px-4 border-b border-border flex items-center">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Dependencies</h2>
          </div>
          <div className="p-4 flex flex-col gap-2">
            {evidence.dependencies.map((dep) => (
              <div key={dep} className="text-[12px] text-[#d4cec2]">{dep}</div>
            ))}
          </div>
        </div>
      </div>

      <div className="bg-surface border border-border rounded-md overflow-hidden mt-3">
        <div className="h-[38px] px-4 border-b border-border flex items-center">
          <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Timeline</h2>
        </div>
        <div className="p-4 flex flex-col gap-0">
          {evidence.timeline.length === 0 && <div className="text-ghost-dim text-xs">No timeline events yet.</div>}
          {evidence.timeline.map((t, i) => {
            const isLatest = i === evidence.timeline.length - 1;
            return (
              <div key={i} className="flex gap-4 text-[12px] relative pb-4 last:pb-0">
                {i < evidence.timeline.length - 1 && (
                  <span className="absolute left-[3px] top-3 bottom-0 w-px bg-[#2b2b2b]" />
                )}
                <span className="text-ghost-dim w-[70px] flex-shrink-0">{fmtTime(t.occurred_at)}</span>
                {isLatest ? (
                  <span className="relative flex h-1.5 w-1.5 mt-1 flex-shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
                  </span>
                ) : (
                  <span className="h-1.5 w-1.5 mt-1 flex-shrink-0 rounded-full bg-[#3c3932]" />
                )}
                <span className="text-[#b8b1a5] -mt-[1px]">{t.message}</span>
              </div>
            );
          })}
        </div>
      </div>

      {evidence.deployments.length > 0 && (
        <div className="bg-surface border border-border rounded-md overflow-hidden mt-3">
          <div className="h-[38px] px-4 border-b border-border flex items-center">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Deployment context</h2>
          </div>
          <div className="p-4 flex flex-col gap-2">
            {evidence.deployments.map((d, i) => (
              <div key={i} className="flex gap-4 text-[12px]">
                <span className="text-ghost-text">{d.service_name}</span>
                <span className="text-ghost-muted">{d.version}</span>
                <span className="text-ghost-dim">{d.minutes_before_incident.toFixed(1)} min before incident</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sim && (
        <div className="bg-surface border border-border rounded-md overflow-hidden mt-3">
          <div className="h-[38px] px-4 border-b border-border flex items-center justify-between">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Simulation</h2>
            <span className="text-[9px] text-ghost-dim">{sim.method} · confidence {sim.confidence_level}</span>
          </div>
          <div className="p-4 flex flex-col gap-4">
            {sim.projections.map((p, i) => (
              <div key={i} className="border border-border rounded p-3">
                <div className="text-[12px] text-ghost-text">
                  {p.edge} <span className="text-ghost-dim">·</span> {p.metric}
                </div>
                <div className="text-[15px] mt-1.5">
                  <span className="text-status-red">{p.current}</span>
                  <span className="text-ghost-dim mx-2">→</span>
                  <span className="text-status-green">~{p.reference}</span>
                </div>
                <div className="text-[10px] text-ghost-dim mt-1">
                  95% CI: [{p.ci_low}, {p.ci_high}]
                </div>
                {p.projected_improvement && (
                  <div className="text-[10px] text-status-green mt-1">
                    projected improvement {fmtPct(p.projected_improvement.point_estimate_pct)}
                    {" "}(95% CI: {fmtPct(p.projected_improvement.ci_95_low_pct)} to {fmtPct(p.projected_improvement.ci_95_high_pct)})
                  </div>
                )}
              </div>
            ))}

            {sim.blast_radius.length > 0 && (
              <div>
                <div className="text-[9px] uppercase tracking-wide text-ghost-dim mb-2">Blast radius</div>
                <div className="flex flex-col gap-2">
                  {sim.blast_radius.map((p, i) => (
                    <div key={i} className="text-[11px] text-ghost-muted flex justify-between border-t border-[#1b1a17] pt-2">
                      <span>{p.edge}</span>
                      <span>{p.current} → ~{p.reference}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {sim?.cohort_comparisons && sim.cohort_comparisons.length > 0 && (
        <div className="bg-surface border border-border rounded-md overflow-hidden mt-3">
          <div className="h-[38px] px-4 border-b border-border flex items-center">
            <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">Cohort comparison</h2>
          </div>
          <div className="p-4 flex flex-col gap-4">
            {sim.cohort_comparisons.map((c, i) => (
              <div key={i} className="border border-border rounded p-3">
                <div className="text-[11px] text-ghost-dim mb-2">
                  {c.edge} · {c.dimension} · last {c.window_minutes}m
                </div>
                <table className="w-full text-[11px] mb-2">
                  <thead>
                    <tr className="text-ghost-dim text-[9px] uppercase">
                      <th className="text-left font-normal py-1">Value</th>
                      <th className="text-right font-normal py-1">Samples</th>
                      <th className="text-right font-normal py-1">Mean latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.cohorts.map((co) => (
                      <tr key={co.value} className="border-t border-[#1b1a17]">
                        <td className="py-1 text-[#d4cec2]">{co.value}</td>
                        <td className="py-1 text-right text-ghost-muted">{co.sample_count}</td>
                        <td className="py-1 text-right text-ghost-text">{co.mean_latency_ms}ms</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {c.comparison && (
                  <div className="text-[11px] text-status-green">
                    cohort {c.comparison.compared_cohort} vs {c.comparison.baseline_cohort}:{" "}
                    {fmtPct(c.comparison.difference_pct)} (95% CI: {fmtPct(c.comparison.ci_95_low_pct)} to{" "}
                    {fmtPct(c.comparison.ci_95_high_pct)})
                    <span className="text-ghost-dim ml-2">{c.comparison.method}</span>
                  </div>
                )}
                {c.note && <div className="text-[11px] text-ghost-dim">{c.note}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}