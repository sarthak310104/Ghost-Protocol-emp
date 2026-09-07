"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError, DemoPreview } from "@/lib/api";
import { GhostLogo } from "@/components/GhostLogo";

const SEVERITY_COLOR: Record<string, string> = {
  critical: "text-status-red",
  high: "text-status-red",
  medium: "text-status-amber",
  low: "text-status-green",
};

export default function LandingPage() {
  const router = useRouter();
  const [preview, setPreview] = useState<DemoPreview | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const demoApiKey = process.env.NEXT_PUBLIC_DEMO_API_KEY;

  useEffect(() => {
    api.demoPreview().then(setPreview).catch(() => setPreview({ configured: false }));
  }, []);

  async function handleDemo() {
    if (!demoApiKey) return;
    setError(null);
    setDemoLoading(true);
    try {
      await api.login(demoApiKey);
      router.push("/overview");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach Ghost Protocol.");
      setDemoLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-16">
      <div className="w-full max-w-lg">
        <div className="flex flex-col items-center gap-4 mb-10 text-center">
          <GhostLogo size={52} />
          <div>
            <div className="text-ghost-text text-[22px] font-display font-semibold tracking-tight">
              Ghost Protocol
            </div>
            <div className="text-ghost-dim text-[10px] tracking-[0.2em] uppercase mt-1">
              behavioral observability
            </div>
          </div>
          <p className="text-ghost-muted text-[14px] leading-relaxed max-w-md">
            Watches how a production system actually behaves, finds structural risk and real
            anomalies, and shows the evidence -- not a guess at root cause.
          </p>
        </div>

        {preview?.configured && (
          <div className="relative bg-surface border border-hud-bright/40 rounded-md p-5 mb-6 overflow-hidden">
            <span className="pointer-events-none absolute top-2 left-2 w-4 h-4 border-t border-l border-hud-bright opacity-70" />
            <span className="pointer-events-none absolute bottom-2 right-2 w-4 h-4 border-b border-r border-hud-bright opacity-70" />

            <div className="flex items-center gap-2 text-ghost-dim text-[9px] uppercase tracking-[0.13em] mb-4">
              Live on the public demo workspace
              <span className="w-1 h-1 rounded-full bg-status-green animate-pulse" />
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4">
              <div>
                <div className="font-display text-[20px] font-semibold text-status-green">
                  {preview.services_observed}
                </div>
                <div className="text-ghost-muted text-[9px] uppercase tracking-wide mt-1">services</div>
              </div>
              <div>
                <div className="font-display text-[20px] font-semibold text-status-red">
                  {preview.open_incident_count}
                </div>
                <div className="text-ghost-muted text-[9px] uppercase tracking-wide mt-1">open incidents</div>
              </div>
              <div>
                <div className="font-display text-[20px] font-semibold text-ghost-text">
                  {preview.top_bottleneck ? Math.round(preview.top_bottleneck.risk_score * 100) : "--"}
                </div>
                <div className="text-ghost-muted text-[9px] uppercase tracking-wide mt-1">
                  top risk{preview.top_bottleneck ? `: ${preview.top_bottleneck.service}` : ""}
                </div>
              </div>
            </div>

            {preview.recent_incidents && preview.recent_incidents.length > 0 && (
              <div className="border-t border-[#1b1a17] pt-3 flex flex-col gap-2">
                {preview.recent_incidents.map((inc, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-status-red opacity-75" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-status-red" />
                    </span>
                    <span className="text-[#ddd7cc]">{inc.title}</span>
                    <span className={`ml-auto text-[8px] uppercase tracking-wide ${SEVERITY_COLOR[inc.severity] ?? "text-ghost-dim"}`}>
                      {inc.severity}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {error && <div className="text-status-red text-xs mb-3 text-center">{error}</div>}

        <div className="flex flex-col gap-3">
          {demoApiKey && (
            <button
              onClick={handleDemo}
              disabled={demoLoading}
              className="bg-ghost-text text-bg text-xs font-medium tracking-wide uppercase
                         rounded py-3 transition-opacity hover:opacity-90
                         disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {demoLoading ? "Connecting..." : "Explore the live demo"}
            </button>
          )}
          <Link
            href="/login"
            className="text-center border border-border text-ghost-muted text-xs uppercase tracking-wide
                       rounded py-3 hover:text-ghost-text hover:border-hud-bright/40 transition-colors"
          >
            Log in with your own key
          </Link>
        </div>

        {demoApiKey && (
          <p className="text-ghost-dim text-[10px] text-center mt-4 leading-relaxed">
            Synthetic traffic on a public workspace -- no signup, no key needed.
          </p>
        )}
      </div>
    </main>
  );
}