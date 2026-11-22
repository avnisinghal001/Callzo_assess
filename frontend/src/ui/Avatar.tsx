import type { Status } from "../api/types.ts";

const PALETTE = [
  ["#c7c3ff", "#4f46e5"], ["#b9ecfb", "#0284a8"], ["#ffd5b8", "#d9480f"], ["#ffc9e3", "#c01f74"],
  ["#d6f5a8", "#4d7c0f"], ["#ffe58f", "#a16207"], ["#bff0de", "#0f766e"], ["#e4ccff", "#7e22ce"],
] as const;

/**
 * A small face whose mood mirrors the account: active smiles, trial is curious, suspended sleeps.
 * Colour and tilt come from the id, so an account looks the same everywhere. Decorative only:
 * the status is always written in words beside it.
 */
export function Avatar({ id, status, size = 40 }: { id: number; status: Status; size?: number }) {
  const [bg, fg] = PALETTE[id % PALETTE.length];
  const tilt = ((id * 37) % 24) - 12;
  const dx = ((id * 13) % 5) - 2;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" className="face shrink-0">
      <rect width="40" height="40" rx="13" fill={bg} />
      <g transform={`translate(${dx} 0) rotate(${tilt} 20 20)`} stroke={fg} strokeWidth="2.6" strokeLinecap="round" fill="none">
        {status === "suspended" ? (
          <><path d="M11.5 18.5q2 2 4 0" /><path d="M24.5 18.5q2 2 4 0" /><path d="M17.5 26.5h5" /></>
        ) : (
          <>
            <circle cx="14" cy="17.5" r="2.1" fill={fg} stroke="none" /><circle cx="26" cy="17.5" r="2.1" fill={fg} stroke="none" />
            {status === "active" ? <path d="M14 23.5q6 6.5 12 0" /> : <circle cx="20" cy="26" r="2.2" />}
          </>
        )}
      </g>
    </svg>
  );
}
