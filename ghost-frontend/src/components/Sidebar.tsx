"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { GhostLogo } from "./GhostLogo";
import { GhostMascot } from "./GhostMascot";
import { Workspace } from "@/lib/api";

const NAV_GROUPS: { label: string; items: { href: string; icon: string; label: string }[] }[] = [
  {
    label: "Monitor",
    items: [
      { href: "/overview", icon: "◈", label: "Overview" },
      { href: "/system-map", icon: "⌘", label: "System Map" },
      { href: "/incidents", icon: "△", label: "Incidents" },
      { href: "/behavior", icon: "∿", label: "Behavior" },
    ],
  },
  {
    label: "Understand",
    items: [
      { href: "/bottlenecks", icon: "◇", label: "Bottlenecks" },
      { href: "/deployments", icon: "↗", label: "Deployments" },
    ],
  },
  {
    label: "Workspace",
    items: [
      { href: "/integrations", icon: "⊙", label: "Integrations" },
      { href: "/settings", icon: "⚙", label: "Settings" },
    ],
  },
];

export function Sidebar({ workspace }: { workspace: Workspace | null }) {
  const pathname = usePathname();
  const asideRef = useRef<HTMLElement>(null);

  // The ghost is anchored to whichever nav item is actually hovered,
  // not the raw cursor Y -- that's what kept it visually misaligned
  // from the item under the pointer. Switching between two different
  // items retreats first, then re-emerges at the new item's position,
  // rather than sliding continuously between them.
  const [ghostY, setGhostY] = useState(60);
  const [ghostVisible, setGhostVisible] = useState(false);
  const hoveredHref = useRef<string | null>(null);
  const retreatTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const RETREAT_MS = 200; // matches GhostMascot's own transition duration

  useEffect(() => {
    return () => {
      if (retreatTimer.current) clearTimeout(retreatTimer.current);
    };
  }, []);

  function popAt(y: number) {
    setGhostY(y);
    setGhostVisible(true);
  }

  function handleItemEnter(e: React.MouseEvent<HTMLAnchorElement>, href: string) {
    if (!asideRef.current) return;
    const itemRect = e.currentTarget.getBoundingClientRect();
    const asideRect = asideRef.current.getBoundingClientRect();
    const y = itemRect.top - asideRect.top + itemRect.height / 2;

    if (retreatTimer.current) clearTimeout(retreatTimer.current);

    if (hoveredHref.current === href) return; // already popped here, no-op

    const wasVisible = hoveredHref.current !== null;
    hoveredHref.current = href;

    if (wasVisible) {
      // switching from one item to another -- retreat, then pop at the new spot
      setGhostVisible(false);
      retreatTimer.current = setTimeout(() => popAt(y), RETREAT_MS);
    } else {
      // nothing was active -- pop straight to this item
      popAt(y);
    }
  }

  function handleSidebarLeave() {
    hoveredHref.current = null;
    if (retreatTimer.current) clearTimeout(retreatTimer.current);
    setGhostVisible(false);
  }

  return (
    <aside
      ref={asideRef}
      onMouseLeave={handleSidebarLeave}
      className="fixed inset-y-0 left-0 w-[214px] border-r border-border bg-bg/95 px-3.5 py-5 z-10"
    >
      <GhostMascot y={ghostY} active={ghostVisible} />
      <div className="flex items-center gap-2 px-2.5 pb-6 border-b border-border font-semibold">
        <GhostLogo size={18} />
        <span>ghost protocol</span>
      </div>

      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <div className="mx-2.5 mt-5 mb-1.5 text-ghost-dim text-[9px] uppercase tracking-[0.15em]">
            {group.label}
          </div>
          {group.items.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                onMouseEnter={(e) => handleItemEnter(e, item.href)}
                className={`h-[34px] flex items-center gap-2.5 px-2.5 rounded transition-colors
                  ${active ? "bg-surface-hi text-ghost-text shadow-[inset_2px_0_0_0_#c95849]" : "text-ghost-muted hover:bg-surface-hi hover:text-[#bbb4a7]"}`}
              >
                <span className={`w-[15px] text-center ${active ? "text-status-red" : "text-[#5b564e]"}`}>
                  {item.icon}
                </span>
                {item.label}
              </Link>
            );
          })}
        </div>
      ))}

      <div className="absolute left-3.5 right-3.5 bottom-4 pt-3.5 border-t border-border text-ghost-muted">
        <div className="flex justify-between">
          <span>workspace</span>
          <b className="text-[#b1aa9d] font-medium">{workspace?.name ?? "..."}</b>
        </div>
        <div className="mt-3 flex items-center gap-1.5">
          <span className="w-[5px] h-[5px] rounded-full bg-status-green animate-pulse" />
          ingestion healthy
        </div>
      </div>
    </aside>
  );
}