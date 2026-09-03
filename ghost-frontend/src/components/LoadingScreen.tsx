"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./LoadingScreen.module.css";

const WORD = "GHOST PROTOCOL";
const TILTS = [-3, 2, -1, 3, -2, 1, 0, -2, 3, -1, 2, -3, 1, 2];
const DRIP_LETTERS = new Set([2, 8, 12]);

type SkellyPhase = "hidden" | "out" | "waving" | "return";

export function LoadingScreen({ label = "booting system" }: { label?: string }) {
  const [phase, setPhase] = useState<SkellyPhase>("hidden");
  const timeouts = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const schedule = (fn: () => void, ms: number) => {
      const id = setTimeout(fn, ms);
      timeouts.current.push(id);
    };

    function runCycle() {
      schedule(() => setPhase("out"), 0);
      schedule(() => setPhase("waving"), 600);
      schedule(() => setPhase("return"), 2600);
      schedule(() => {
        setPhase("hidden");
        schedule(runCycle, 3200);
      }, 3200);
    }

    schedule(runCycle, 2300);

    return () => {
      timeouts.current.forEach(clearTimeout);
      timeouts.current = [];
    };
  }, []);

  const walking = phase === "out" || phase === "return";
  const walkerClass = [
    styles.walker,
    phase !== "hidden" ? styles.walkerVisible : "",
    phase === "out" || phase === "waving" ? styles.walkerOut : "",
    phase === "return" ? styles.walkerReturn : "",
  ].join(" ");
  const bobClass = [styles.bob, walking ? styles.bobWalking : "", phase === "waving" ? styles.bobWaving : ""].join(" ");

  let letterIndex = 0;

  return (
    <div className={styles.stage}>
      <div className={styles.title}>
        {[...WORD].map((ch, i) => {
          if (ch === " ") {
            return <span key={i} style={{ width: 14, display: "inline-block" }} />;
          }
          const idx = letterIndex++;
          const isFirst = idx === 0;
          return (
            <span
              key={i}
              className={styles.letter}
              style={{
                // @ts-expect-error -- CSS custom property, not a standard React style key
                "--tilt": `${TILTS[idx % TILTS.length]}deg`,
                animationDelay: `${idx * 0.06}s`,
              }}
            >
              {ch}
              {DRIP_LETTERS.has(idx) && (
                <span
                  className={styles.drip}
                  style={{
                    left: 10 + (idx % 3) * 6,
                    height: 10 + (idx % 3) * 6,
                    animationDelay: `${idx * 0.06 + 0.4}s`,
                  }}
                />
              )}
              {isFirst && (
                <span className={styles.anchor}>
                  <span className={walkerClass}>
                    <span className={bobClass}>
                      <span className={styles.shadow} />
                      <span className={styles.skSkull}>
                        <span className={`${styles.skEye} ${styles.skEyeL}`} />
                        <span className={`${styles.skEye} ${styles.skEyeR}`} />
                        <span className={`${styles.skCheek} ${styles.skCheekL}`} />
                        <span className={`${styles.skCheek} ${styles.skCheekR}`} />
                        <span className={styles.skSmile} />
                      </span>
                      <span className={styles.skBody} />
                      <span className={`${styles.skArm} ${styles.skArmL}`} />
                      <span className={`${styles.skArm} ${styles.skArmR}`} />
                      <span className={`${styles.skLeg} ${styles.skLegL}`} />
                      <span className={`${styles.skLeg} ${styles.skLegR}`} />
                    </span>
                  </span>
                </span>
              )}
            </span>
          );
        })}
      </div>

      <div className={styles.subtitle}>observe · model · detect · simulate</div>

      <div className={styles.hint}>
        {label}
        <span className={styles.hintDot} />
      </div>
    </div>
  );
}