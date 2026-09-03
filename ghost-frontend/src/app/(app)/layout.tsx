"use client";

import { Sidebar } from "@/components/Sidebar";
import { LoadingScreen } from "@/components/LoadingScreen";
import { useWorkspace } from "@/lib/useWorkspace";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { workspace, checking } = useWorkspace();

  if (checking) {
    return <LoadingScreen label="checking session" />;
  }

  if (!workspace) return null; // redirect to /login already in flight

  return (
    <div className="flex min-h-screen">
      <Sidebar workspace={workspace} />
      <main className="ml-[214px] w-full max-w-[1500px] px-9 pt-6 pb-16">{children}</main>
    </div>
  );
}