"use client";

import { useEffect, useState } from "react";
import { api, ApiError, SyntheticCheck, SyntheticCheckResult } from "@/lib/api";

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function ResultDot({ result }: { result: SyntheticCheckResult }) {
  const title = result.success
    ? `${result.status_code ?? "ok"} -- ${result.latency_ms?.toFixed(0) ?? "?"}ms -- ${new Date(result.ran_at).toLocaleTimeString()}`
    : `${result.error ?? result.status_code ?? "failed"} -- ${new Date(result.ran_at).toLocaleTimeString()}`;
  return (
    <span
      title={title}
      className={`inline-block w-2 h-2 rounded-full ${result.success ? "bg-status-green" : "bg-status-red"}`}
    />
  );
}

function CheckRow({
  check,
  onDelete,
  deleting,
}: {
  check: SyntheticCheck;
  onDelete: () => void;
  deleting: boolean;
}) {
  const [results, setResults] = useState<SyntheticCheckResult[] | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  async function loadHistory() {
    try {
      const r = await api.syntheticCheckResults(check.id, 30);
      setResults(r);
    } catch {
      setResults([]);
    }
  }

  return (
    <div className="bg-surface border border-border rounded-md p-4">
      <div className="flex items-center gap-3">
        {check.failing ? (
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
          </span>
        ) : (
          <span className="w-1.5 h-1.5 rounded-full bg-status-green" />
        )}
        <span className="text-ghost-text text-[14px]">{check.name}</span>
        <span className="text-ghost-dim text-[10px] truncate max-w-[280px]">
          {check.method} {check.url}
        </span>
        {check.failing && (
          <span className="text-status-red text-[9px] uppercase tracking-wide border border-status-red/40 rounded px-1.5 py-0.5">
            failing
          </span>
        )}
        <button
          onClick={() => {
            setShowHistory((s) => !s);
            if (!showHistory && results === null) loadHistory();
          }}
          className="ml-auto text-ghost-dim text-[10px] uppercase tracking-wide hover:text-ghost-text transition-colors"
        >
          {showHistory ? "Hide history" : "History"}
        </button>
        <button
          onClick={onDelete}
          disabled={deleting}
          className="text-ghost-dim text-[10px] uppercase tracking-wide hover:text-status-red transition-colors disabled:opacity-40"
        >
          {deleting ? "Removing..." : "Remove"}
        </button>
      </div>

      <div className="grid grid-cols-4 gap-4 mt-4">
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Last probed</div>
          <div className="text-ghost-text text-[13px] mt-1">{timeAgo(check.last_probed_at)}</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Consecutive failures</div>
          <div className={`text-[13px] mt-1 ${check.consecutive_failures > 0 ? "text-status-amber" : "text-ghost-text"}`}>
            {check.consecutive_failures} / {check.failure_threshold}
          </div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Interval</div>
          <div className="text-ghost-text text-[13px] mt-1">{check.interval_seconds}s</div>
        </div>
        <div>
          <div className="text-ghost-dim text-[9px] uppercase tracking-wide">Expected status</div>
          <div className="text-ghost-text text-[13px] mt-1">
            {check.expected_status_min}-{check.expected_status_max}
          </div>
        </div>
      </div>

      {showHistory && (
        <div className="mt-4 pt-3 border-t border-border">
          {results === null ? (
            <div className="text-ghost-dim text-[11px]">Loading...</div>
          ) : results.length === 0 ? (
            <div className="text-ghost-dim text-[11px]">No probes recorded yet.</div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {results
                .slice()
                .reverse()
                .map((r, i) => (
                  <ResultDot key={i} result={r} />
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SyntheticChecksPage() {
  const [checks, setChecks] = useState<SyntheticCheck[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [intervalSeconds, setIntervalSeconds] = useState("60");
  const [failureThreshold, setFailureThreshold] = useState("2");
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function load() {
    try {
      const data = await api.syntheticChecks();
      setChecks(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load synthetic checks");
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createSyntheticCheck({
        name: name.trim(),
        url: url.trim(),
        interval_seconds: parseInt(intervalSeconds, 10),
        failure_threshold: parseInt(failureThreshold, 10),
      });
      setName("");
      setUrl("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to register check");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await api.deleteSyntheticCheck(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove check");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Monitor</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Synthetic Checks</h1>
        <div className="text-ghost-muted mt-2">
          Everything else here is passive -- it analyzes telemetry that already arrived. A service
          that crashes and goes completely silent produces no telemetry at all, so nothing else can
          see it. Synthetic checks close that gap by actively probing a URL on a schedule and opening
          a real incident when the probe itself starts failing, independent of whether any traffic
          is flowing.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      <form onSubmit={handleCreate} className="bg-surface border border-border rounded-md p-4 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">Register a check</div>
        <div className="grid grid-cols-4 gap-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name"
            required
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-service/health"
            required
            type="url"
            className="col-span-2 bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={intervalSeconds}
            onChange={(e) => setIntervalSeconds(e.target.value)}
            placeholder="Interval (s)"
            required
            type="number"
            min="10"
            max="3600"
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
        </div>
        <div className="grid grid-cols-4 gap-3 mt-3">
          <input
            value={failureThreshold}
            onChange={(e) => setFailureThreshold(e.target.value)}
            placeholder="Failure threshold"
            required
            type="number"
            min="1"
            max="10"
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
          A 2xx response is treated as healthy by default. Private and internal addresses are allowed
          (this is a self-hosted deployment) -- only link-local targets (cloud metadata endpoints) are
          rejected.
        </p>
      </form>

      {checks === null && !error && <div className="text-ghost-dim text-xs">Loading...</div>}

      {checks !== null && checks.length === 0 && (
        <div className="bg-surface border border-border rounded-md p-4 text-ghost-dim text-xs">
          No synthetic checks registered yet -- add one above to start probing a service on a schedule.
        </div>
      )}

      <div className="flex flex-col gap-3">
        {checks?.map((c) => (
          <CheckRow
            key={c.id}
            check={c}
            onDelete={() => handleDelete(c.id)}
            deleting={deletingId === c.id}
          />
        ))}
      </div>
    </>
  );
}