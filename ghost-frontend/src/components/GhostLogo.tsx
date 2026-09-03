export function GhostLogo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg">
      <g stroke="#ece8de" strokeWidth={1.8}>
        <line x1={38} y1={34} x2={17} y2={17} />
        <line x1={38} y1={34} x2={56} y2={16} />
        <line x1={38} y1={34} x2={21.2} y2={44.9} />
        <line x1={38} y1={34} x2={55} y2={53} />
      </g>
      {/* hub node, largest, highest fan-in */}
      <circle cx={38} cy={34} r={8} fill="none" stroke="#ece8de" strokeWidth={2.6} />
      {/* smallest node, minor leaf service */}
      <circle cx={17} cy={17} r={3.5} fill="none" stroke="#ece8de" strokeWidth={2} />
      {/* mid-size healthy nodes */}
      <circle cx={56} cy={16} r={4.6} fill="none" stroke="#ece8de" strokeWidth={2} />
      <circle cx={21.2} cy={44.9} r={3.6} fill="none" stroke="#ece8de" strokeWidth={2} />
      {/* anomalous node */}
      <circle cx={55} cy={53} r={5.2} fill="#cf5a4b" stroke="#cf5a4b" strokeWidth={2} />
    </svg>
  );
}