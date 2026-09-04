"use client";

import { useEffect, useRef } from "react";
import styles from "./LoadingScreen.module.css";

const WORD = "GHOST PROTOCOL";

// Roughly how long the letters + subtitle + hint take to finish
// staggering in (last letter's delay + its own animation + the hint's
// own fade-up) -- used as the "seen it once" minimum so the parent
// layout doesn't swap in real content before the title has actually
// finished appearing.
const MIN_VISIBLE_MS = 2200;

export function LoadingScreen({
  label = "booting system",
  onFirstCycleComplete,
}: {
  label?: string;
  onFirstCycleComplete?: () => void;
}) {
  const firedOnce = useRef(false);

  useEffect(() => {
    const id = setTimeout(() => {
      if (!firedOnce.current) {
        firedOnce.current = true;
        onFirstCycleComplete?.();
      }
    }, MIN_VISIBLE_MS);
    return () => clearTimeout(id);
  }, [onFirstCycleComplete]);

  let letterIndex = 0;

  return (
    <div className={styles.stage}>
      <div className={styles.titleFrame}>
        <div className={styles.title}>
          {[...WORD].map((ch, i) => {
            if (ch === " ") {
              return <span key={i} style={{ width: 14, display: "inline-block" }} />;
            }
            const idx = letterIndex++;
            return (
              <span
                key={i}
                className={styles.letter}
                style={{ animationDelay: `${idx * 0.05}s` }}
              >
                {ch}
              </span>
            );
          })}
        </div>
        {/* One-shot -- sweeps across exactly once while the letters are
            still rendering in, not a looping decorative radar. Tied to
            the actual reveal moment (a scan literally rendering the
            title into existence), which is what makes it a
            justified use of the effect rather than ambient motion for
            its own sake. */}
        <div className={styles.scanBeam} />
      </div>

      <div className={styles.subtitle}>observe · model · detect · simulate</div>

      <div className={styles.bootBar}>
        <div className={styles.bootBarFill} style={{ animationDuration: `${MIN_VISIBLE_MS}ms` }} />
      </div>

      <div className={styles.hint}>
        {label}
        <span className={styles.hintDot} />
      </div>
    </div>
  );
}