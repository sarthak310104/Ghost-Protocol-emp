"use client";

import { useEffect, useState } from "react";
import { api, ApiError, ReasoningConfig } from "@/lib/api";

export default function IntegrationsPage() {
  const [config, setConfig] = useState<ReasoningConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [endpointUrl, setEndpointUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [providerLabel, setProviderLabel] = useState("custom");
  const [saving, setSaving] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  async function load() {
    try {
      setConfig(await api.reasoningConfig());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load integration status");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.configureReasoning(endpointUrl.trim(), apiKey.trim(), providerLabel.trim() || "custom");
      setEndpointUrl("");
      setApiKey("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    setError(null);
    try {
      await api.disconnectReasoning();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to disconnect");
    } finally {
      setDisconnecting(false);
    }
  }

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Optional</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Integrations</h1>
        <div className="text-ghost-muted mt-2">
          Ghost Protocol implements no reasoning itself -- point it at any external analysis
          service that implements the expected request/response contract, and it&apos;ll be called
          with an incident&apos;s evidence whenever a new incident opens. Everything else in Ghost
          (ingestion, the behavioral graph, anomaly detection, structural risk, statistical
          simulation) works fully without this configured.
        </div>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}

      {config && (
        <div className="relative bg-surface border border-hud-bright/40 rounded-md p-4 mb-6 overflow-hidden">
          <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-70" />
          <span className="pointer-events-none absolute bottom-2 right-2 w-4 h-4 border-b border-r border-hud-bright opacity-70" />
          <div className="flex items-center gap-2 text-ghost-dim text-[9px] uppercase tracking-[0.13em] mb-2">
            Status
            <span className={`w-1 h-1 rounded-full ${config.configured ? "bg-status-green animate-pulse" : "bg-ghost-dim"}`} />
          </div>
          {config.configured ? (
            <>
              <div className="text-ghost-text text-[14px]">{config.reasoning_provider_label}</div>
              <div className="text-ghost-muted text-[12px] mt-1 break-all">{config.reasoning_endpoint_url}</div>
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="text-status-red text-[11px] uppercase tracking-wide mt-3 hover:opacity-70 transition-opacity disabled:opacity-40"
              >
                {disconnecting ? "Disconnecting..." : "Disconnect"}
              </button>
            </>
          ) : (
            <div className="text-ghost-dim text-[13px]">Not configured</div>
          )}
        </div>
      )}

      <form onSubmit={handleSave} className="bg-surface border border-border rounded-md p-4">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">
          {config?.configured ? "Reconfigure" : "Connect a reasoning service"}
        </div>
        <div className="flex flex-col gap-3">
          <input
            value={endpointUrl}
            onChange={(e) => setEndpointUrl(e.target.value)}
            placeholder="https://your-analysis-service.example.com/analyze"
            required
            type="url"
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="API key for that service"
            required
            type="password"
            className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                       focus:outline-none focus:border-hud-bright transition-colors"
          />
          <input
            value={providerLabel}
            onChange={(e) => setProviderLabel(e.target.value)}
            placeholder="Label (e.g. custom, openai-proxy) -- informational only"
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
          The key is encrypted at rest and never shown again after saving -- not even to you.
        </p>
      </form>
    </>
  );
}