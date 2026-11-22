import { useId, type InputHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon.tsx";

function FieldError({ id, text }: { id: string; text?: string }) {
  if (!text) return null;
  return <p id={id} className="rise flex items-start gap-1.5 text-sm font-medium text-suspended-ink"><Icon name="error" size={17} className="mt-0.5" />{text}</p>;
}

/** Label, hint and error wired to the control, so assistive tech reads them together. */
export function TextField({ label, hint, error, icon, value, onValue, ...rest }: {
  label: string; hint?: string; error?: string; icon?: IconName; value: string; onValue: (v: string) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value">) {
  const id = useId();
  const describedBy = [hint && `${id}h`, error && `${id}e`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold">{label}</label>
      <div className="relative">
        {icon && <Icon name={icon} size={19} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />}
        <input id={id} autoComplete="off" value={value} onChange={(e) => onValue(e.target.value)} aria-invalid={Boolean(error)} aria-describedby={describedBy}
          className={`min-h-12 w-full rounded-2xl border-2 bg-tile pr-4 text-base font-medium transition-colors placeholder:font-normal placeholder:text-muted ${icon ? "pl-11" : "pl-4"} ${error ? "border-suspended" : "border-line hover:border-line-strong focus:border-primary"}`} {...rest} />
      </div>
      {hint && <p id={`${id}h`} className="text-sm text-muted">{hint}</p>}
      <FieldError id={`${id}e`} text={error} />
    </div>
  );
}

/** Native radios as big, friendly choices. Arrow keys work as in any radio group. */
export function ChoiceField({ label, error, value, options, onValue, className }: {
  label: string; error?: string; value: string; onValue: (v: string) => void; className: string;
  options: { value: string; label: string; icon?: IconName; emoji?: string }[];
}) {
  const id = useId();
  return (
    <div role="radiogroup" aria-labelledby={`${id}l`} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}e` : undefined} className="grid gap-2">
      <p id={`${id}l`} className="text-sm font-semibold">{label}</p>
      <div className={`grid gap-2 ${className}`}>
        {options.map((o) => {
          const on = value === o.value;
          return (
            <label key={o.value}
              className={`group relative flex min-h-14 cursor-pointer items-center gap-3 rounded-2xl border-2 px-3.5 py-2.5 text-sm font-semibold transition-[background,border-color,transform] duration-200 ease-spring hover:-translate-y-0.5 has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary/50 ${on ? "border-primary bg-primary-soft" : error ? "border-suspended/50 bg-tile" : "border-line bg-tile hover:border-line-strong"}`}>
              <input type="radio" name={id} value={o.value} checked={on} onChange={() => onValue(o.value)} className="sr-only" />
              {o.icon && <span className={`face grid size-9 place-items-center rounded-xl transition-colors ${on ? "bg-primary text-white" : "bg-card text-ink"}`}><Icon name={o.icon} size={20} /></span>}
              {o.emoji && <span className="face text-xl" aria-hidden="true">{o.emoji}</span>}
              <span className="min-w-0 flex-1">{o.label}</span>
              {on && <Icon name="check" size={18} strokeWidth={2.6} className="pop text-primary" />}
            </label>
          );
        })}
      </div>
      <FieldError id={`${id}e`} text={error} />
    </div>
  );
}
