import { useState } from "react";
import { Link } from "react-router-dom";
import { login } from "../lib/api";
import Logo from "../components/Logo";

const DEMO = [
  {
    who: "Patient",
    id: "9000000001",
    name: "Sunita, 42 · Kolar",
    note: "9 months of acidity · 3 doctors · 0 tests",
  },
  {
    who: "Clinician",
    id: "meera@kolarchc.gov.in",
    name: "Dr Meera Rao",
    note: "Kolar CHC · 4 patients with live consent",
  },
  {
    who: "Admin",
    id: "admin@aira.health",
    name: "Operations",
    note: "No clinical read access, by design",
  },
];
const DEMO_PASS = "aira-demo-2026";

export default function Login() {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [showDemo, setShowDemo] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(identifier.trim(), password);
    } catch (err) {
      setError(err.detail || err.message);
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] lg:grid lg:grid-cols-[1.1fr_1fr]">
      {/* ── the argument. On a phone it is a compact banner; on a desktop it
             is the half of the screen that explains why this exists. ────── */}
      <section className="relative bg-forest-900 text-white overflow-hidden">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-forest-700/50 blur-3xl"
        />
        <div className="relative px-6 pt-7 pb-8 sm:px-10 lg:px-14 lg:py-16 lg:min-h-[100dvh] flex flex-col">
          <Logo tone="light" size={32} />

          <div className="mt-8 lg:mt-auto lg:pt-16 max-w-lg">
            <p className="text-forest-300 text-[10px] sm:text-xs font-bold uppercase tracking-[.2em]">
              AI Risk &amp; Awareness Assistant
            </p>
            <h1 className="mt-3 text-[1.65rem] leading-[1.15] sm:text-3xl lg:text-[2.7rem] lg:leading-[1.1] font-extrabold">
              Nobody missed the symptom.
              <br />
              <span className="text-forest-300">Everybody missed the pattern.</span>
            </h1>

            <p className="mt-5 text-sm sm:text-base text-forest-100/80 leading-relaxed">
              Three doctors each saw one visit for indigestion, and each made a
              reasonable call. No one saw that it was the third visit, the third
              antacid, and that nobody had ever ordered a test.
            </p>

            {/* The three numbers ARE the pitch. They sit above the fold on a
                phone, because that is the only screen most people will see. */}
            <dl className="mt-7 grid grid-cols-3 gap-3 sm:gap-5 border-t border-white/15 pt-6">
              {[
                ["190", "days of symptoms"],
                ["3", "doctors seen"],
                ["0", "tests ordered"],
              ].map(([n, l]) => (
                <div key={l}>
                  <dt className="nums text-2xl sm:text-3xl font-extrabold">{n}</dt>
                  <dd className="text-[10px] sm:text-[11px] uppercase tracking-wider text-forest-300 mt-1 leading-tight">
                    {l}
                  </dd>
                </div>
              ))}
            </dl>

            <ul className="mt-8 hidden lg:block space-y-2.5 text-xs text-forest-300/90">
              {[
                "Rules decide. Models rank. The AI only phrases what the rules already decided.",
                "Every clinical claim carries the guideline it came from.",
                "No record opens without a consent artefact the patient issued.",
              ].map((line) => (
                <li key={line} className="flex gap-2.5">
                  <span className="text-forest-300 mt-px">—</span>
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ── the form ─────────────────────────────────────────────────────── */}
      <section className="px-6 py-9 sm:px-10 lg:px-14 lg:py-16 flex flex-col justify-center">
        <div className="w-full max-w-sm mx-auto">
          <h2 className="text-xl sm:text-2xl font-extrabold tracking-tight">
            Sign in
          </h2>
          <p className="text-sm text-ink-soft mt-1.5">
            Phone number if you are a patient. Email if you are staff.
          </p>

          <form onSubmit={submit} className="mt-7 space-y-4">
            <div>
              <label className="label" htmlFor="identifier">
                Phone or email
              </label>
              <input
                id="identifier"
                className="field"
                autoComplete="username"
                inputMode="email"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder="9000000001"
                required
              />
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                type="password"
                className="field"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && (
              <p
                role="alert"
                className="text-sm text-tier-high bg-tier-high/[.07] rounded-xl px-4 py-3"
              >
                {error}
              </p>
            )}

            <button className="btn-primary w-full !py-3.5" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-5 text-sm text-ink-soft">
            New here?{" "}
            <Link to="/signup" className="font-semibold text-forest-700 underline">
              Create an account
            </Link>
          </p>

          {/* Collapsed by default so the login form is the page, not the demo
              scaffolding around it. One tap on stage. */}
          <div className="mt-9 border-t border-paper-line pt-5">
            <button
              type="button"
              onClick={() => setShowDemo((s) => !s)}
              className="flex w-full items-center justify-between text-[11px] font-semibold uppercase tracking-[.09em] text-ink-faint hover:text-ink"
            >
              Demo accounts
              <span className={`transition-transform ${showDemo ? "rotate-180" : ""}`}>
                ⌄
              </span>
            </button>

            {showDemo && (
              <div className="mt-3 space-y-2">
                {DEMO.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => {
                      setIdentifier(d.id);
                      setPassword(DEMO_PASS);
                    }}
                    className="w-full text-left card px-4 py-3 hover:border-forest-300 active:scale-[.99] transition"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-forest-600">
                        {d.who}
                      </span>
                      <span className="font-mono text-[10px] text-ink-faint truncate max-w-[55%]">
                        {d.id}
                      </span>
                    </div>
                    <span className="block text-sm font-semibold mt-0.5">{d.name}</span>
                    <span className="block text-xs text-ink-faint">{d.note}</span>
                  </button>
                ))}
                <p className="pt-1 text-[11px] text-ink-faint">
                  Seeded by <code className="font-mono">py -3.11 demo/seed.py</code>.
                  Tap one to fill the form.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
