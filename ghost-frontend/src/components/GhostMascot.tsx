/**
 * The sidebar companion -- distinct from GhostLogo (the actual brand
 * mark, the asymmetric node-graph). This is Concept A, the angular
 * ghost silhouette, kept in reserve specifically for this interaction
 * rather than used as the logo itself.
 */
export function GhostMascot({ y, active }: { y: number; active: boolean }) {
  return (
    <div
      className="pointer-events-none absolute right-[-13px] z-20 transition-[transform,opacity] duration-200 ease-out"
      style={{
        top: y,
        transform: active ? "translate(16px, -50%)" : "translate(-30px, -50%)",
        opacity: active ? 1 : 0,
      }}
    >
      <svg width="22" height="26" viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg">
        <path
          d="M36 6 C50 6 60 17 60 32 L60 58 L51 50 L44 58 L36 50 L28 58 L21 50 L12 58 L12 32 C12 17 22 6 36 6 Z"
          fill="#090908"
          stroke="#ece8de"
          strokeWidth={3}
          strokeLinejoin="round"
        />
        <circle cx={27} cy={30} r={3.2} fill="#cf5a4b" />
        <circle cx={45} cy={30} r={3.2} fill="#cf5a4b" />
      </svg>
    </div>
  );
}