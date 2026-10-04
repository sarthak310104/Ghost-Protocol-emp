"use client";

import { useEffect, useState } from "react";
import { api, ApiError, SLODefinition, SLOStatus } from "@/lib/api";

function pct(n: number | null, digits = 2): string {
  return n === null ? "--" : `${n.toFixed(digits)}%`;
}

function budgetColor(remaining: number | null): string {
  if (remaining === null) return "text-ghost-dim";
  if (remaining < 0) return "text-status-red";
  if (remaining < 25) return "text-status-amber";
  return "text-status-green";
}

function burnLabel(status: SLOStatus): string {
  if (status.burn_rate_1h === null) return "no traffic this hour";
  return `${status.burn_rate_1h.toFixed(1)}x`;
}

function SLORow({
  definition,
  status,
  onDelete,
  deleting,
}: {
  definition: SLODefinition;
  status: SLOStatus | undefined;
  onDelete: () => void;
  deleting: boolean;
}) {
  const remaining = status?.error_budget_remaining_percent ?? null;
  const fastBurning = status?.is_fast_burning ?? false;

  return (
    <div className="bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        {fastBurning ? (
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
          </span>
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-status-green" />
        )}
        <span className="text-ghost-text text-[14px]">{definition.service_name}</span>
        <span className="text-ghost-dim text-[10px]">
          {definition.target_percent}% target over {definition.window_days}d
        </span>
        {definition.alerting && (
          <span className="text-status-red text-[9px] uppercase tracking-wide border border-status-red/40 rounded px-1.5 py-0.5">
            alerting
          </span>
        )}
        <button
          onClick={onDelete}
          disabled={deleting}
          className="ml-auto text-ghost-dim text-[10px] uppercase tracking-wide hover:text-status-red transition-colors disabled:opacity-40"
        >
          {deleting ? "Removing..." : "Remove"}
        </button>
      </div>

      <div className="grid grid-cols-4 gap-4 mt-4">
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Actual</div>
          <div className="text-ghost-text text-[13px] mt-1">{pct(status?.actual_percent ?? null)}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Budget remaining</div>
          <div className={`text-[13px] mt-1 ${budgetColor(remaining)}`}>{pct(remaining, 1)}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Burn rate (1h)</div>
          <div className={`text-[13px] mt-1 ${fastBurning ? "text-status-red" : "text-ghost-text"}`}>
            {status ? burnLabel(status) : "--"}
          </div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Requests / errors</div>
          <div className="text-ghost-text text-[13px] mt-1">
            {status ? `${status.total_count} / ${status.error_count}` : "--"}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SLOsPage() {
  const [definitions, setDefinitions] = useState<SLODefinition[] | null>(null);
  const [statuses, setStatuses] = useState<SLOStatus[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [serviceName, setServiceName] = useState("");
  const [targetPercent, setTargetPercent] = useState("99.9");
  const [windowDays, setWindowDays] = useState("30");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    try {
      const [defs, stats] = await Promise.all([api.slos(), api.sloStatus()]);
      setDefinitions(defs);
      setStatuses(stats);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load SLOs");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleDefine(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.defineSlo(serviceName.trim(), parseFloat(targetPercent), parseInt(windowDays, 10));
      setServiceName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to define SLO");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.deleteSlo(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove SLO");
    } finally {
      setDeletingId(null);
    }
  }

  const statusByService = new Map((statuses ?? []).map((s) => [s.service_name, s]));

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Understand</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">SLOs</h1>
        <div className="text-ghost-muted mt-2">
          Define an error-budget target per service; Ghost tracks consumption from hourly
          rollups and pushes a notification through your configured webhook the moment a
          service is burning its budget fast enough to blow it before the window ends --
          once per burn, not a recurring digest. No check-interval to configure: alerting
          runs on the same hourly tick everything else here does.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      <form onSubmit={handleDefine} className="bg-surface border border-border rounded-md p-4 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">Define an SLO</div>
        <div className="grid grid-cols-3 gap-3">
          <input
            value={serviceName}
            onChange={(e) => setServiceName(e.target.value)}
            placeholder="Service name"
            required
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={targetPercent}
            onChange={(e) => setTargetPercent(e.target.value)}
            placeholder="Target % (e.g. 99.9)"
            required
            type="number"
            step="0.01"
            min="0.01"
            max="100"
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={windowDays}
            onChange={(e) => setWindowDays(e.target.value)}
            placeholder="Window (days)"
            required
            type="number"
            step="1"
            min="1"
            max="90"
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
        </div>
        <button
          type="submit"
          disabled={saving}
          className="mt-3 bg-ghost-text text-bg text-[11px] font-medium tracking-wide uppercase
                     rounded px-4 py-2 transition-opacity hover:opacity-90
                     disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        <p className="text-ghost-dim text-[10px] mt-3 leading-relaxed">
          Re-defining an existing service&apos;s SLO updates it in place and resets its alert cooldown.
        </p>
      </form>

      {definitions === null && !error && <div className="text-ghost-dim text-xs">Loading...</div>}

      {definitions !== null && definitions.length === 0 && (
        <div className="bg-surface border border-border rounded-md p-4 text-ghost-dim text-xs">
          No SLOs defined yet -- add one above to start tracking its error budget.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {definitions?.map((d) => (
          <SLORow
            key={d.id}
            definition={d}
            status={statusByService.get(d.service_name)}
            onDelete={() => handleDelete(d.id)}
            deleting={deletingId === d.id}
          />
        ))}
      </div>
    </>
  );
}