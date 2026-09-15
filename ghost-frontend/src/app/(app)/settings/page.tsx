"use client";

import { useEffect, useState } from "react";
import { api, ApiError, WorkspaceSettings } from "@/lib/api";

function timeAgo(iso: string | null): string {
  if (!iso) return "never used";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreatedKey, setJustCreatedKey] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  async function load() {
    try {
      setSettings(await api.workspaceSettings());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load settings");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const created = await api.createApiKey(newLabel.trim() || "default");
      setJustCreatedKey(created.api_key);
      setNewLabel("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create key");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(id: string) {
    setRevokingId(id);
    try {
      await api.revokeApiKey(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to revoke key");
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <>
      <div className="mt-1 mb-6">
        <div className="text-ghost-dim text-[10px] uppercase tracking-[0.13em]">Workspace</div>
        <h1 className="font-display text-[25px] font-semibold tracking-tight mt-2">Settings</h1>
      </div>

      {error && <div className="text-status-red text-xs mb-4">{error}</div>}
      {settings === null && !error && <div className="text-ghost-dim text-xs">Loading...</div>}

      {settings && (
        <>
          <div className="bg-surface border border-border rounded-md p-4 mb-6">
            <div className="text-ghost-dim text-[9px] uppercase tracking-wide mb-2">Workspace name</div>
            <div className="text-ghost-text text-[15px]">{settings.name}</div>
            <div className="text-ghost-dim text-[11px] mt-2">Created {fmtDate(settings.created_at)}</div>
          </div>

          {justCreatedKey && (
            <div className="relative bg-surface border border-hud-bright/40 rounded-md p-4 mb-6 overflow-hidden">
              <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-70" />
              <span className="pointer-events-none absolute bottom-2 right-2 w-4 h-4 border-b border-r border-hud-bright opacity-70" />
              <div className="text-status-amber text-[10px] uppercase tracking-wide mb-2">
                Copy this now -- it won&apos;t be shown again
              </div>
              <code className="block bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px] break-all">
                {justCreatedKey}
              </code>
              <button
                onClick={() => setJustCreatedKey(null)}
                className="text-ghost-dim text-[10px] mt-2 hover:text-ghost-text transition-colors"
              >
                Dismiss
              </button>
            </div>
          )}

          <div className="bg-surface border border-border rounded-md overflow-hidden mb-6">
            <div className="h-[43px] px-4 border-b border-border flex items-center">
              <h2 className="text-[10px] uppercase tracking-[0.11em] font-medium">API keys</h2>
            </div>
            <div className="p-4 flex flex-col gap-3">
              {settings.api_keys.map((k) => (
                <div key={k.id} className="flex items-center gap-3 text-[13px]">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${k.is_active ? "bg-status-green" : "bg-ghost-dim"}`} />
                  <span className="text-ghost-text">{k.label}</span>
                  <span className="text-ghost-dim text-[10px]">created {fmtDate(k.created_at)}</span>
                  <span className="text-ghost-dim text-[10px]">last used {timeAgo(k.last_used_at)}</span>
                  {k.is_active ? (
                    <button
                      onClick={() => handleRevoke(k.id)}
                      disabled={revokingId === k.id}
                      className="ml-auto text-status-red text-[10px] uppercase tracking-wide hover:opacity-70 transition-opacity disabled:opacity-40"
                    >
                      {revokingId === k.id ? "Revoking..." : "Revoke"}
                    </button>
                  ) : (
                    <span className="ml-auto text-ghost-dim text-[10px] uppercase tracking-wide">Revoked</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          <form onSubmit={handleCreate} className="bg-surface border border-border rounded-md p-4">
            <div className="text-ghost-dim text-[10px] uppercase tracking-[0.11em] mb-3">Create a new key</div>
            <div className="flex gap-3">
              <input
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="e.g. ci-pipeline"
                className="flex-1 bg-bg border border-border rounded px-3 py-2 text-ghost-text text-[12px]
                           focus:outline-none focus:border-hud-bright transition-colors"
              />
              <button
                type="submit"
                disabled={creating}
                className="bg-ghost-text text-bg text-[11px] font-medium tracking-wide uppercase
                           rounded px-4 py-2 transition-opacity hover:opacity-90
                           disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </form>
        </>
      )}
    </>
  );
}