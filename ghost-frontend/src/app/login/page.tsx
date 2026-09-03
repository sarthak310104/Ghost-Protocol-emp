"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { GhostLogo } from "@/components/GhostLogo";

export default function LoginPage() {
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(apiKey);
      router.push("/overview");
    } catch (err) {
      if (err instanceof ApiError) {
        // Same generic message the backend sends for every failure
        // reason -- deliberately not distinguishing "wrong key" from
        // "rate limited" from "workspace deleted" here in the UI copy
        // either, beyond what the backend itself already discloses.
        setError(err.status === 429 ? "Too many attempts -- try again shortly." : err.message);
      } else {
        setError("Could not reach Ghost Protocol. Is the backend running?");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center gap-3 mb-8">
          <GhostLogo size={44} />
          <div className="text-ghost-text font-semibold tracking-tight">ghost protocol</div>
          <div className="text-ghost-dim text-[10px] tracking-[0.2em] uppercase">
            behavioral observability
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="relative bg-surface border border-border rounded-md p-6 flex flex-col gap-4"
        >
          {/* corner reticle, same restrained HUD touch as the dashboard's featured panels */}
          <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-60" />
          <span className="pointer-events-none absolute bottom-2 right-2 w-4 h-4 border-b border-r border-hud-bright opacity-60" />

          <label className="flex flex-col gap-2">
            <span className="text-ghost-muted text-[10px] uppercase tracking-[0.1em]">
              Workspace API key
            </span>
            <input
              type="password"
              autoComplete="off"
              autoFocus
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="ghost_live_..."
              className="bg-bg border border-border rounded px-3 py-2 text-ghost-text text-sm
                         focus:outline-none focus:border-hud-bright transition-colors"
            />
          </label>

          {error && <div className="text-status-red text-xs">{error}</div>}

          <button
            type="submit"
            disabled={loading || apiKey.length === 0}
            className="bg-ghost-text text-bg text-xs font-medium tracking-wide uppercase
                       rounded py-2.5 mt-2 transition-opacity hover:opacity-90
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? "Connecting..." : "Connect"}
          </button>
        </form>

        <p className="text-ghost-dim text-[10px] text-center mt-6 leading-relaxed">
          Your API key is exchanged for a session and never stored in the browser.
        </p>
      </div>
    </main>
  );
}