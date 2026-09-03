export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] gap-2 text-center">
      <div className="text-ghost-text text-sm">{title}</div>
      <div className="text-ghost-dim text-[10px]">Not built yet -- next up.</div>
    </div>
  );
}