import { ICONS } from "./iconData.ts";

type Shape =
  | { d: string }
  | { cx: string; cy: string; r: string }
  | { cx: string; cy: string; rx: string; ry: string };

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 18, className = "", strokeWidth = 1.8 }: {
  name: IconName; size?: number; className?: string; strokeWidth?: number;
}) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" focusable="false"
      className={`shrink-0 ${name === "spinner" ? "motion-safe:animate-spin" : ""} ${className}`}
    >
      {(ICONS[name] as readonly Shape[]).map((s, i) =>
        "d" in s ? <path key={i} d={s.d} />
        : "r" in s ? <circle key={i} cx={s.cx} cy={s.cy} r={s.r} />
        : <ellipse key={i} cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} />,
      )}
    </svg>
  );
}
