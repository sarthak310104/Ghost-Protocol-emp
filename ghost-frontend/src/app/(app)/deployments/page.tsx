"use client";

import { useEffect, useState } from "react";
import { api, ApiError, ConfigDrift, Deployment, GraphEdge, RetrospectiveResult } from "@/lib/api";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtPct(n: number): string {
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

function diffColor(n: number): string {
  if (n < -5) return "text-status-green"; // meaningfully faster
  if (n > 5) return "text-status-red"; // meaningfully slower
  return "text-ghost-text";
}

// Inline, one row at a time -- picks which edge to compare (a service
// can be the caller on several), then runs the before/after comparison
// against the drift event's own changed_at. Collapsed by default since
// most drift rows won't be worth digging into.
function RetrospectivePanel({
  serviceName,
  changedAt,
  edges,
}: {
  serviceName: string;
  changedAt: string;
  edges: GraphEdge[];
}) {
  const [open, setOpen] = useState(false);
  const callerEdges = edges.filter((e) => e.caller === serviceName);
  const [callee, setCallee] = useState(callerEdges[0]?.callee ?? "");
  const [result, setResult] = useState<RetrospectiveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!callee) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.retrospectiveComparison(serviceName, callee, changedAt));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to compare");
    } finally {
      setLoading(false);
    }
  }

  if (callerEdges.length === 0) {
    // This service only appears as a callee on every known edge (or
    // isn't in the graph at all yet) -- nothing to pick a comparison
    // edge from.
    return null;
  }

  return (
    <div className="ml-3 mt-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-hud-bright text-[10px] uppercase tracking-wide hover:opacity-70 transition-opacity"
      >
        {open ? "Hide comparison" : "Compare impact"}
      </button>

      {open && (
        <div className="mt-2 bg-bg border border-border rounded p-3 max-w-md">
          <div className="flex items-center gap-2">
            <span className="text-ghost-dim text-[10px]">{serviceName} →</span>
            <select
              value={callee}
              onChange={(e) => setCallee(e.target.value)}
              className="bg-surface border border-border rounded px-2 py-1 text-ghost-text text-[11px]
                         focus:outline-none focus:border-hud-bright transition-colors"
            >
              {callerEdges.map((e) => (
                <option key={e.callee} value={e.callee}>{e.callee}</option>
              ))}
            </select>
            <button
              onClick={run}
              disabled={loading}
              className="ml-auto bg-ghost-text text-bg text-[10px] font-medium tracking-wide uppercase
                         rounded px-3 py-1 transition-opacity hover:opacity-90
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? "Running..." : "Run"}
            </button>
          </div>

          {error && <div className="text-status-red text-[11px] mt-2">{error}</div>}

          {result && (
            <div className="mt-3 text-[11px]">
              {result.comparison ? (
                <>
                  <div className={`font-display text-[16px] font-semibold ${diffColor(result.comparison.difference_pct)}`}>
                    {fmtPct(result.comparison.difference_pct)} latency
                  </div>
                  <div className="text-ghost-dim text-[10px] mt-0.5">
                    95% CI {fmtPct(result.comparison.ci_95_low_pct)} to {fmtPct(result.comparison.ci_95_high_pct)}
                  </div>
                  <div className="grid grid-cols-2 gap-3 mt-2">
                    <div>
                      <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Before</div>
                      <div className="text-ghost-text mt-0.5">
                        {result.before!.mean_latency_ms}ms · {result.before!.sample_count} samples
                      </div>
                    </div>
                    <div>
                      <div className="text-ghost-dim text-[9px] uppercase tracking-wide">After</div>
                      <div className="text-ghost-text mt-0.5">
                        {result.after!.mean_latency_ms}ms · {result.after!.sample_count} samples
                      </div>
                    </div>
                  </div>
                  <div className="text-ghost-dim text-[10px] mt-2 leading-relaxed">
                    Before/after on one timeline -- weaker evidence than a concurrent cohort,
                    since anything else that changed in this window is baked into the difference too.
                  </div>
                </>
              ) : (
                <div className="text-ghost-dim">{result.note}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DeploymentsPage() {
  const [deployments, setDeployments] = useState<Deployment[] | null>(null);
  const [drift, setDrift] = useState<Record<string, ConfigDrift[]> | null>(null);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.graph().then(setEdges).catch(() => {}); // used only to populate the comparison picker -- a failure here shouldn't blank the page

    api
      .deployments()
      .then(async (rows) => {
        setDeployments(rows);
        // One drift call per distinct service, not per deployment row --
        // the computation is already per-service, and a service with many
        // recorded deploys shouldn't mean many redundant calls for it.
        const serviceNames = Array.from(new Set(rows.map((d) => d.service_name)));
        const results = await Promise.all(
          serviceNames.map((name) =>
            api.configDrift(name).catch(() => [] as ConfigDrift[]) // one service's failure shouldn't blank the page
          )
        );
        const bySer: Record<string, ConfigDrift[]> = {};
        serviceNames.forEach((name, i) => { bySer[name] = results[i]; });
        setDrift(bySer);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load deployments"));
  }, []);

  const driftEntries = drift ? Object.entries(drift).filter(([, entries]) => entries.length > 0) : [];

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Change history</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Deployments</h1>
        <div className="text-ghost-muted mt-2">
          Every deploy a CI/CD pipeline has recorded -- what Ghost checks for correlation when an
          incident opens shortly after.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      <div className="bg-surface border border-border rounded-md overflow-hidden">
        {deployments === null && <div className="p-4 text-ghost-dim text-xs">Loading...</div>}
        {deployments !== null && deployments.length === 0 && (
          <div className="p-4 text-ghost-dim text-xs">
            No deployments recorded yet -- point your CI/CD pipeline at{" "}
            <code className="text-ghost-text">POST /v1/deployments</code> right after a deploy completes.
          </div>
        )}

        <div className="p-4 flex flex-col gap-0">
          {deployments?.map((d, i) => (
            <div key={d.id} className="flex gap-4 text-[12px] relative pb-4 last:pb-0">
              {deployments && i < deployments.length - 1 && (
                <span className="absolute left-[3px] top-3 bottom-0 w-px bg-[#2b2b2b]" />
              )}
              <span className="h-1.5 w-1.5 mt-1 flex-shrink-0 rounded-full bg-status-green" />
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <span className="text-ghost-text">{d.service_name}</span>
                  <span className="text-ghost-muted">{d.version}</span>
                  <span className="ml-auto text-ghost-dim text-[10px]">{fmtTime(d.deployed_at)}</span>
                </div>
                {d.notes && <div className="text-ghost-muted text-[11px] mt-1">{d.notes}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {driftEntries.length > 0 && (
        <div className="bg-surface border border-border rounded-md overflow-hidden mt-4">
          <div className="h-[38px] px-4 border-b border-border flex items-center">
            <h2 className="text-[10px] uppercase tracking-[0.13em] font-medium">Config drift</h2>
          </div>
          <div className="px-4 pt-3 text-[11px] text-ghost-dim">
            Config values currently sitting on something other than what they held
            in an earlier deployment -- not limited to the most recent deploy, since
            a change several deploys back can still be live and relevant. This is a
            candidate list, not a claim that any one value (or combination) is a
            problem on its own.
          </div>
          <div className="p-4 flex flex-col gap-4">
            {driftEntries.map(([serviceName, entries]) => (
              <div key={serviceName}>
                <div className="text-ghost-muted text-[11px] mb-1.5">{serviceName}</div>
                <div className="flex flex-col gap-1.5">
                  {entries.map((d, i) => (
                    <div key={i} className="pl-3 border-l border-border">
                      <div className="flex gap-4 text-[12px] items-baseline">
                        <span className="text-ghost-text w-[140px] flex-shrink-0 truncate">{d.key}</span>
                        <span className="flex items-baseline gap-2">
                          <span className="text-ghost-dim line-through">{d.previous_value ?? "(unset)"}</span>
                          <span className="text-ghost-dim">→</span>
                          <span className="text-ghost-text">{d.current_value ?? "(removed)"}</span>
                        </span>
                        <span className="ml-auto text-ghost-dim text-[10px] whitespace-nowrap">
                          since {d.version_at_change} · {fmtTime(d.changed_at)} ·{" "}
                          {d.deployments_since_change} deploy{d.deployments_since_change === 1 ? "" : "s"} ago
                        </span>
                      </div>
                      <RetrospectivePanel serviceName={serviceName} changedAt={d.changed_at} edges={edges} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}