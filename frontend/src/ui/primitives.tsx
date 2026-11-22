import { useEffect, useRef, useState, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import type { Plan, Status } from "../api/types.ts";
import { PLAN_LABEL, STATUS_LABEL } from "../lib/format.ts";
import { Icon, type IconName } from "./Icon.tsx";

// Looks follow BoardUI's button, chip, card and segmented control (MIT), on native elements.

type Variant = "primary" | "secondary" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_1px_2px_rgb(23_23_28/0.2)] hover:bg-primary-strong disabled:bg-faint disabled:shadow-none",
  secondary: "bg-tile text-ink border border-line shadow-tile hover:border-line-strong hover:bg-card disabled:text-faint disabled:shadow-none",
  ghost: "text-muted hover:bg-ink/5 hover:text-ink disabled:text-faint",
};

export function Button({ variant = "secondary", icon, busy, children, className = "", disabled, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; icon?: IconName; busy?: boolean }) {
  return (
    <button type="button" disabled={disabled || busy} aria-busy={busy || undefined}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold transition-[background,border-color,transform] duration-150 active:scale-[0.97] ${VARIANTS[variant]} ${className}`} {...rest}>
      {busy ? <Icon name="spinner" size={17} /> : icon && <Icon name={icon} size={17} />}
      {children}
    </button>
  );
}

export function IconButton({ icon, label, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string }) {
  return (
    <button type="button" aria-label={label} title={label}
      className={`grid size-11 place-items-center rounded-xl transition-[background,transform] duration-150 hover:bg-ink/10 active:scale-90 disabled:opacity-30 ${className}`} {...rest}>
      <Icon name={icon} size={20} />
    </button>
  );
}

type Tone = "info" | "warning" | "danger";
const TONES: Record<Tone, { box: string; icon: IconName }> = {
  info: { box: "bg-primary-soft text-ink", icon: "info" },
  warning: { box: "bg-trial-soft text-trial-ink", icon: "warning" },
  danger: { box: "bg-suspended-soft text-suspended-ink", icon: "error" },
};

export function Banner({ tone = "info", title, children, actions, role }: {
  tone?: Tone; title?: string; children?: ReactNode; actions?: ReactNode; role?: "alert" | "status";
}) {
  return (
    <div role={role} className={`rise flex flex-wrap items-center gap-3 rounded-2xl px-4 py-3 text-sm ${TONES[tone].box}`}>
      <Icon name={TONES[tone].icon} size={20} />
      <div className="min-w-[12rem] flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div>{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-2 text-ink">{actions}</div>}
    </div>
  );
}

export const Skeleton = ({ className = "" }: { className?: string }) => <div aria-hidden="true" className={`skeleton ${className}`} />;

export function Card({ children, className = "", ...rest }: { children: ReactNode } & HTMLAttributes<HTMLElement>) {
  return <section className={`rounded-3xl bg-card ${className}`} {...rest}>{children}</section>;
}

export const STATUS_ICON: Record<Status, IconName> = { active: "smile", trial: "hourglass", suspended: "moon" };
const STATUS_CHIP: Record<Status, string> = {
  active: "bg-active-soft text-active-ink",
  trial: "bg-trial-soft text-trial-ink",
  suspended: "bg-suspended-soft text-suspended-ink",
};

/** Status never relies on colour alone: icon and word too. */
export function StatusChip({ status }: { status: Status }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1 text-xs font-semibold ${STATUS_CHIP[status]}`}>
      <Icon name={STATUS_ICON[status]} size={14} strokeWidth={2.2} />{STATUS_LABEL[status]}
    </span>
  );
}

const PLAN_CHIP: Record<Plan, string> = {
  basic: "bg-[#e3f3ee] text-[#115e59]",
  pro: "bg-[#dfeaff] text-[#1e40af]",
  enterprise: "bg-[#f1e4ff] text-[#6b21a8]",
};

export function PlanChip({ plan }: { plan: Plan }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-2 py-1 text-xs font-semibold ${PLAN_CHIP[plan]}`}>
      <Icon name={plan} size={14} strokeWidth={2} />{PLAN_LABEL[plan]}
    </span>
  );
}

/** Native select dressed as a pill. Tinted while it is narrowing the results. */
export function PillSelect({ label, icon, active, children, className = "", ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; icon?: IconName; active?: boolean }) {
  return (
    <div className={`relative ${className}`}>
      {icon && <Icon name={icon} size={16} className={`pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 ${active ? "text-primary" : "text-muted"}`} />}
      <select aria-label={label} {...rest}
        className={`min-h-11 w-full appearance-none rounded-xl border pr-8 text-sm font-semibold shadow-tile transition-colors ${icon ? "pl-9" : "pl-3"} ${active ? "border-primary/40 bg-primary-soft text-primary-strong" : "border-line bg-tile hover:border-line-strong"}`}>
        {children}
      </select>
      <Icon name="down" size={15} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-muted" />
    </div>
  );
}

/** Briefly highlights its content when the live value changes. Not on first paint. */
export function Live({ value, children }: { value: number; children: ReactNode }) {
  const prev = useRef(value);
  const [bump, setBump] = useState(0);
  useEffect(() => {
    if (prev.current !== value) { prev.current = value; setBump((b) => b + 1); }
  }, [value]);
  return <span key={bump} className={bump ? "changed" : undefined}>{children}</span>;
}
