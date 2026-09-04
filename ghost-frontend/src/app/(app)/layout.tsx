"use client";

import { useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useWorkspace } from "@/lib/useWorkspace";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { workspace, checking } = useWorkspace();
  const [hasShownOnce, setHasShownOnce] = useState(false);

  // Two independent things have to both be true before real content
  // shows: the session check itself finished (`!checking`), AND the
  // loading screen's own animation has completed at least one full
  // walk-out/wave/walk-back-in cycle (`hasShownOnce`). Gating on only
  // the first one is what let the animation get cut off mid-cycle
  // whenever the session check happened to resolve faster than the
  // ~5.5s a full loop takes -- if the check finishes first, this still
  // holds the loading screen up (and it keeps looping) until its own
  // cycle finishes; if the check is slow, the loading screen just
  // keeps looping until it is.
  const showLoading = checking || !hasShownOnce;

  if (showLoading) {
    return <LoadingScreen label="checking session" onFirstCycleComplete={() => setHasShownOnce(true)} />;
  }

  if (!workspace) return null; // redirect to /login already in flight

  return (
    <div className="flex min-h-screen">
      <Sidebar workspace={workspace} />
      <main className="ml-[214px] w-full max-w-[1500px] px-9 pt-6 pb-16">{children}</main>
    </div>
  );
}