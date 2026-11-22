import { useEffect, useRef, useState, useSyncExternalStore } from "react";

export function useMediaQuery(q: string): boolean {
  return useSyncExternalStore(
    (cb) => { const m = window.matchMedia(q); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); },
    () => window.matchMedia(q).matches,
  );
}

export const useReducedMotion = () => useMediaQuery("(prefers-reduced-motion: reduce)");

/** Rolls a number to its new value. Adapted from BoardUI's use-count-up (MIT). */
export function useCountUp(target: number, duration = 380): number {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = from.current;
    if (start === target) return;
    if (reduced) { from.current = target; setShown(target); return; }
    const t0 = performance.now();
    let raf = requestAnimationFrame(function tick(now) {
      const t = Math.min(1, Math.max(0, (now - t0) / duration));
      from.current = start + (target - start) * (1 - (1 - t) ** 3);
      setShown(from.current);
      if (t < 1) raf = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(raf);
  }, [target, duration, reduced]);
  return shown;
}
