import { tier as tierOf } from "../lib/ui";

export function Spinner({ label = "Loading" }) {
  return (
    <div className="flex items-center gap-3 py-16 justify-center text-ink-faint text-sm">
      <span className="h-4 w-4 rounded-full border-2 border-forest-300 border-t-forest-700 animate-spin" />
      {label}
    </div>
  );
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="card p-5 border-tier-high/25 bg-tier-high/[.04]">
      <p className="text-sm font-semibold text-tier-high">
        {error.status === 403
          ? "You do not have access to this."
          : "Something went wrong."}
      </p>
      <p className="mt-1 text-sm text-ink-soft">{error.detail || error.message}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn-ghost mt-4 !py-2 !px-4">
          Try again
        </button>
      )}
    </div>
  );
}

export function TierChip({ value, clinical = false }) {
  const t = tierOf(value);
  return (
    <span className={`chip ${t.soft}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${t.bg}`} />
      {clinical ? t.clinical : t.label}
    </span>
  );
}

/** A progress ring. The arc is how far a symptom has travelled through its
 *  own safe window - not a score, and never a probability. */
export function Ring({ value, color, size = 84, stroke = 8, children }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#e5e1d8"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, tone = "" }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-[.09em] text-ink-faint">
        {label}
      </p>
      <p className={`nums text-2xl font-bold mt-1 ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-ink-faint mt-0.5">{sub}</p>}
    </div>
  );
}

export function Empty({ icon = "○", title, body }) {
  return (
    <div className="card p-10 text-center">
      <div className="text-3xl text-forest-300">{icon}</div>
      <p className="mt-3 font-semibold">{title}</p>
      {body && <p className="mt-1 text-sm text-ink-soft max-w-sm mx-auto">{body}</p>}
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide = false }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-ink/40 p-0 sm:p-6"
      onClick={onClose}
    >
      <div
        className={`bg-paper-card w-full ${
          wide ? "sm:max-w-3xl" : "sm:max-w-lg"
        } max-h-[90vh] overflow-y-auto rounded-t-xl2 sm:rounded-xl2 shadow-lift`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-paper-card border-b border-paper-line px-6 py-4 flex items-center justify-between">
          <h2 className="font-bold">{title}</h2>
          <button
            onClick={onClose}
            className="text-ink-faint hover:text-ink text-xl leading-none px-2"
            aria-label="Close"
          >
            ×
          </button>
        </div>
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}

/** The provenance line. Every clinical claim in this product carries one, and
 *  that is the difference between a guideline engine and a chatbot. */
export function Citation({ source, section, quote }) {
  if (!source) return null;
  return (
    <details className="mt-2 group">
      <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[.08em] text-forest-600 hover:text-forest-900">
        {source}
        {section ? ` ${section}` : ""}
      </summary>
      {quote && (
        <blockquote className="mt-2 border-l-2 border-forest-300 pl-3 text-xs italic text-ink-soft">
          {quote}
        </blockquote>
      )}
    </details>
  );
}
