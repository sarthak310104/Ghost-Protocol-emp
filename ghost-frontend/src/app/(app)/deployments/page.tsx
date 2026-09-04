"use client";

import { useEffect, useState } from "react";
import { api, Deployment, ApiError } from "@/lib/api";

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function DeploymentsPage() {
  const [deployments, setDeployments] = useState<Deployment[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .deployments()
      .then(setDeployments)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load deployments"));
  }, []);

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
    </>
  );
}