import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { getSession, logout } from "../../lib/api";
import { useLiveUpdates } from "../../lib/ws";
import { LanguagePicker, useLang } from "../../lib/lang";
import Logo from "../../components/Logo";

/**
 * Navigation.
 *
 * Five slots on the bottom bar, because a sixth is a mis-tap on a 5-inch
 * screen held in one hand. The four screens someone actually opens are the
 * four that get a slot; everything periodic lives behind More.
 */
const PRIMARY = [
  { to: "/app", end: true, key: "home", label: "Home", icon: HomeIcon },
  { to: "/app/ask", key: "ask", label: "Ask", icon: AskIcon },
  { to: "/app/reports", key: "reports", label: "Reports", icon: ReportIcon },
  { to: "/app/card", key: "card", label: "Card", icon: CardIcon },
];

const SECONDARY = [
  { to: "/app/notes", key: "from_your_doctor", hintKey: "hint_notes",
    label: "From your doctor", hint: "Notes written for you after a visit" },
  { to: "/app/timeline", key: "your_story", hintKey: "hint_timeline",
    label: "Your story", hint: "Everything, in order" },
  { to: "/app/screening", key: "free_checks", hintKey: "hint_screening",
    label: "Free checks", hint: "Government screening you can have" },
  { to: "/app/access", key: "who_can_see", hintKey: "hint_access",
    label: "Who can see your record", hint: "Consent, and how to take it back" },
];

export default function PatientShell() {
  const nav = useNavigate();
  const loc = useLocation();
  const s = getSession();
  const [toast, setToast] = useState(null);
  const [more, setMore] = useState(false);
  const { t } = useLang();

  useEffect(() => setMore(false), [loc.pathname]);

  useLiveUpdates((event, payload) => {
    if (event === "consent.requested")
      setToast({
        kind: "consent",
        text: `${payload.doctor_name || "A clinician"} is asking to see your record.`,
        to: "/app/access",
        cta: "Decide",
      });
    if (event === "note.released")
      setToast({
        kind: "note",
        text: `${payload.doctor_name || "Your doctor"} has sent you a note.`,
        to: "/app/notes",
        cta: "Read it",
      });
    if (event === "record.updated")
      setToast({ kind: "info", text: "Your clinician updated your record." });
  });

  const onSecondary = SECONDARY.some((x) => loc.pathname.startsWith(x.to));

  return (
    <div className="min-h-[100dvh] pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:pb-0">
      <header className="sticky top-0 z-30 bg-paper/90 backdrop-blur border-b border-paper-line">
        <div className="max-w-5xl mx-auto px-4 sm:px-5 h-14 flex items-center justify-between gap-3">
          <Logo size={26} />

          <nav className="hidden sm:flex items-center gap-1">
            {[...PRIMARY, ...SECONDARY.slice(0, 2)].map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `rounded-full px-3.5 py-2 text-sm font-semibold transition ${
                    isActive ? "bg-forest-900 text-white" : "text-ink-soft hover:bg-forest-50"
                  }`
                }
              >
                {t(n.key, n.label)}
              </NavLink>
            ))}
            <button
              onClick={() => setMore((m) => !m)}
              className={`rounded-full px-3.5 py-2 text-sm font-semibold transition ${
                more ? "bg-forest-50 text-ink" : "text-ink-soft hover:bg-forest-50"
              }`}
            >
              {t("more", "More")}
            </button>
          </nav>

          <div className="flex items-center gap-2 sm:gap-3">
            {/* Always reachable, on every screen, in every state. Someone who
                cannot read the current language must never have to navigate
                through it to escape it. */}
            <LanguagePicker />
            <span className="hidden md:block text-sm font-semibold truncate max-w-[10rem]">
              {s?.display_name}
            </span>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="hidden sm:block text-xs font-semibold text-ink-faint hover:text-ink"
            >
              {t("sign_out", "Sign out")}
            </button>
          </div>
        </div>
      </header>

      {toast && (
        <div className="max-w-5xl mx-auto px-4 sm:px-5 pt-4">
          <div
            className={`card p-4 flex items-start gap-3 ${
              toast.kind === "info" ? "" : "border-forest-500 bg-forest-50"
            }`}
          >
            <span className="text-forest-700 text-lg leading-none mt-px">●</span>
            <p className="text-sm flex-1">{toast.text}</p>
            {toast.to && (
              <button
                onClick={() => {
                  nav(toast.to);
                  setToast(null);
                }}
                className="text-xs font-bold text-forest-700 underline shrink-0"
              >
                {toast.cta}
              </button>
            )}
            <button
              onClick={() => setToast(null)}
              className="text-ink-faint text-lg leading-none shrink-0"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      )}

      <main className="max-w-5xl mx-auto px-4 sm:px-5 py-5 sm:py-6">
        <Outlet />
      </main>

      {/* ── More: a sheet on phones, a dropdown on desktop ──────────────── */}
      {more && (
        <div
          className="fixed inset-0 z-40 bg-ink/30 flex items-end sm:items-start sm:justify-end sm:pt-16 sm:pr-8"
          onClick={() => setMore(false)}
        >
          <div
            className="w-full sm:w-80 bg-paper-card rounded-t-xl2 sm:rounded-xl2 shadow-lift p-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]"
            onClick={(e) => e.stopPropagation()}
          >
            {SECONDARY.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className="block rounded-xl px-4 py-3.5 hover:bg-forest-50"
              >
                <span className="block font-semibold text-sm">{t(n.key, n.label)}</span>
                <span className="block text-xs text-ink-faint mt-0.5">
                  {t(n.hintKey, n.hint)}
                </span>
              </NavLink>
            ))}

            <div className="mt-1 border-t border-paper-line px-4 pt-3 pb-1 flex items-center justify-between gap-3 sm:hidden">
              <span className="text-xs font-semibold text-ink-faint">
                {t("language", "Language")}
              </span>
              <LanguagePicker />
            </div>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="sm:hidden w-full text-left rounded-xl px-4 py-3.5 font-semibold text-sm text-ink-faint hover:bg-forest-50"
            >
              {t("sign_out", "Sign out")}
            </button>
          </div>
        </div>
      )}

      {/* ── bottom bar. This app is used one-handed on a cheap phone. ───── */}
      <nav className="sm:hidden fixed bottom-0 inset-x-0 z-30 bg-paper-card border-t border-paper-line pb-[env(safe-area-inset-bottom)]">
        <div className="grid grid-cols-5">
          {PRIMARY.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 py-2.5 text-[10px] font-semibold ${
                  isActive ? "text-forest-900" : "text-ink-faint"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <n.icon active={isActive} />
                  {t(n.key, n.label)}
                </>
              )}
            </NavLink>
          ))}
          <button
            onClick={() => setMore(true)}
            className={`flex flex-col items-center gap-1 py-2.5 text-[10px] font-semibold ${
              onSecondary ? "text-forest-900" : "text-ink-faint"
            }`}
          >
            <MoreIcon active={onSecondary} />
            {t("more", "More")}
          </button>
        </div>
      </nav>
    </div>
  );
}

/* Line icons rather than emoji: emoji render differently on every Android
   skin, and half of them arrive as a fallback box on a budget device. */
const stroke = (active) => ({
  fill: "none",
  stroke: "currentColor",
  strokeWidth: active ? 2.1 : 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
});

function Svg({ children, active }) {
  return (
    <svg width="21" height="21" viewBox="0 0 24 24" aria-hidden="true" {...stroke(active)}>
      {children}
    </svg>
  );
}

function HomeIcon({ active }) {
  return (
    <Svg active={active}>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20h14V9.5" />
    </Svg>
  );
}
function AskIcon({ active }) {
  return (
    <Svg active={active}>
      <path d="M21 12a8 8 0 0 1-8 8H7l-4 3 1.2-4.4A8 8 0 1 1 21 12Z" />
      <path d="M9.5 9.8a2.6 2.6 0 1 1 3.4 2.5c-.6.2-.9.7-.9 1.3" />
      <path d="M12 16.6h.01" />
    </Svg>
  );
}
function ReportIcon({ active }) {
  return (
    <Svg active={active}>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h4" />
    </Svg>
  );
}
function CardIcon({ active }) {
  return (
    <Svg active={active}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="M3 10h18M7 14.5h5" />
    </Svg>
  );
}
function MoreIcon({ active }) {
  return (
    <Svg active={active}>
      <circle cx="5" cy="12" r="1.4" />
      <circle cx="12" cy="12" r="1.4" />
      <circle cx="19" cy="12" r="1.4" />
    </Svg>
  );
}
