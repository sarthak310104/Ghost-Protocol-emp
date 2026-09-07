"use client";

import { useEffect, useState } from "react";
import { api, ApiError, CohortDimension, CohortAnalysisResult } from "@/lib/api";

interface Found {
  key: string;
  edge: string;
  dimensionLabel: string;
  result: CohortAnalysisResult;
}

function ComparisonBar({ pct }: { pct: number }) {
  const [width, setWidth] = useState(0);
  const improving = pct < 0;
  const magnitude = Math.min(100, Math.abs(pct));

  useEffect(() => {
    const id = requestAnimationFrame(() => setWidth(magnitude));
    return () => cancelAnimationFrame(id);
  }, [magnitude]);

  return (
    <div className="h-[3px] bg-[#1b1a17] mt-3 rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-[width] duration-700 ease-out ${improving ? "bg-status-green" : "bg-status-red"}`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

function ComparisonCard({ found }: { found: Found }) {
  const { result } = found;
  const c = result.comparison!;
  const improving = c.difference_pct < 0;

  return (
    <div className="relative bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        <span className="text-ghost-text text-[13px]">{found.edge}</span>
        <span className="text-ghost-dim text-[10px]">{found.dimensionLabel}</span>
        <span className={`ml-auto font-display text-[18px] font-semibold ${improving ? "text-status-green" : "text-status-red"}`}>
          {c.difference_pct > 0 ? "+" : ""}
          {c.difference_pct.toFixed(1)}%
        </span>
      </div>

      <ComparisonBar pct={c.difference_pct} />

      <div className="flex items-center gap-4 mt-3 text-[11px] text-ghost-muted">
        <span>
          <span className="text-ghost-text">{c.baseline_cohort}</span> vs{" "}
          <span className="text-ghost-text">{c.compared_cohort}</span>
        </span>
        <span className="ml-auto">
          95% CI [{c.ci_95_low_pct.toFixed(1)}%, {c.ci_95_high_pct.toFixed(1)}%]
        </span>
      </div>

      <div className="flex items-center gap-4 mt-2 text-[10px] text-ghost-dim">
        {result.cohorts.map((s) => (
          <span key={s.value}>
            {s.value}: n={s.sample_count}
          </span>
        ))}
        <span className="ml-auto">{c.method}</span>
      </div>
    </div>
  );
}

function RegisterDimensionForm({ onRegistered }: { onRegistered: () => void }) {
  const [attributeKey, setAttributeKey] = useState("");
  const [label, setLabel] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.registerCohortDimension(attributeKey.trim(), label.trim());
      setAttributeKey("");
      setLabel("");
      onRegistered();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to register dimension");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-surface border border-border rounded-md p-4">
      <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">Track a new dimension</div>
      <div className="grid grid-cols-2 gap-3">
        <input
          value={attributeKey}
          onChange={(e) => setAttributeKey(e.target.value)}
          placeholder="config.redis_ttl_seconds"
          required
          className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                     focus:outline-none focus:border-hud-bright transition-colors"
        />
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Redis TTL (seconds)"
          required
          className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                     focus:outline-none focus:border-hud-bright transition-colors"
        />
      </div>
      {error && <div className="text-status-red text-[11px] mt-2">{error}</div>}
      <button
        type="submit"
        disabled={submitting}
        className="mt-3 bg-ghost-text text-bg text-[11px] font-medium tracking-wide uppercase
                   rounded px-4 py-2 transition-opacity hover:opacity-90
                   disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {submitting ? "Registering..." : "Register"}
      </button>
      <p className="text-ghost-dim text-[10px] mt-3 leading-relaxed">
        The attribute key an already-tagged span attribute (e.g. a canary rollout's config value).
        Nothing changes at ingestion -- if spans already carry this, it's queryable immediately.
      </p>
    </form>
  );
}

export default function CohortsPage() {
  const [dimensions, setDimensions] = useState<CohortDimension[] | null>(null);
  const [found, setFound] = useState<Found[]>([]);
  const [pending, setPending] = useState<{ edge: string; dimensionLabel: string; note: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [dims, edges] = await Promise.all([api.cohortDimensions(), api.graph()]);
      setDimensions(dims);

      if (dims.length === 0 || edges.length === 0) {
        setFound([]);
        setPending([]);
        setLoading(false);
        return;
      }

      // Auto-discovers real comparisons across every known edge and
      // registered dimension, rather than making the person manually
      // pick a caller/callee/dimension combination -- Ghost surfaces
      // what's actually real, the person doesn't configure a dashboard
      // to go find it.
      const uniqueEdges = Array.from(new Set(edges.map((e) => `${e.caller}->${e.callee}`))).map((s) => {
        const [caller, callee] = s.split("->");
        return { caller, callee };
      });

      const results = await Promise.all(
        dims.flatMap((dim) =>
          uniqueEdges.map(async ({ caller, callee }) => {
            try {
              const result = await api.cohortAnalysis(caller, callee, dim.attribute_key);
              return { dim, caller, callee, result };
            } catch {
              return null;
            }
          })
        )
      );

      const realFound: Found[] = [];
      const stillPending: { edge: string; dimensionLabel: string; note: string }[] = [];
      for (const r of results) {
        if (!r) continue;
        const edgeLabel = `${r.caller}->${r.callee}`;
        if (r.result.comparison) {
          realFound.push({ key: `${edgeLabel}:${r.dim.attribute_key}`, edge: edgeLabel, dimensionLabel: r.dim.label, result: r.result });
        } else if (r.result.cohorts.length > 0) {
          stillPending.push({ edge: edgeLabel, dimensionLabel: r.dim.label, note: r.result.note ?? "Gathering data." });
        }
      }
      setFound(realFound);
      setPending(stillPending);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load cohort data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, []);

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Concurrent comparison</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Cohorts</h1>
        <div className="text-ghost-muted mt-2">
          Compares whatever config values are currently co-occurring on the same call path -- a canary
          at 8% of traffic against the rest, observed over the same window. Stronger evidence than
          before/after, since both cohorts run concurrently and aren&apos;t confounded by whatever else
          changed that week -- still an association, not a randomized experiment.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {loading && <div className="text-ghost-dim text-xs mb-4">Loading...</div>}

      {!loading && found.length > 0 && (
        <div className="flex flex-col gap-3 mb-6">
          {found.map((f) => (
            <ComparisonCard key={f.key} found={f} />
          ))}
        </div>
      )}

      {!loading && found.length === 0 && dimensions !== null && dimensions.length > 0 && (
        <div className="text-ghost-dim text-xs mb-6">
          {pending.length > 0
            ? "Dimension registered, but no comparison is statistically valid yet -- still gathering samples."
            : "No concurrent cohort data on any known edge yet."}
        </div>
      )}

      {!loading && pending.length > 0 && (
        <div className="bg-surface border border-border rounded-md p-4 mb-6">
          <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">Gathering data</div>
          <div className="flex flex-col gap-2">
            {pending.map((p, i) => (
              <div key={i} className="flex items-center gap-3 text-[11px]">
                <span className="text-ghost-text">{p.edge}</span>
                <span className="text-ghost-dim">{p.dimensionLabel}</span>
                <span className="ml-auto text-ghost-dim">{p.note}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <RegisterDimensionForm onRegistered={loadAll} />
    </>
  );
}