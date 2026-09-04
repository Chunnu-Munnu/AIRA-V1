import { useState } from "react";
import { Link } from "react-router-dom";
import { signupDoctor, signupPatient } from "../lib/api";
import Logo from "../components/Logo";

// These are the only risk factors AIRA collects. Caste, religion, income and
// region are absent from the schema entirely - not hidden, not optional,
// absent - so that no model trained on this data can ever learn them.
const RISK = [
  ["tobacco_smoking", "Smokes, or used to smoke"],
  ["tobacco_chewing", "Chews tobacco, gutka or paan"],
  ["alcohol_heavy", "Drinks alcohol regularly"],
  ["family_history_cancer", "Cancer in the immediate family"],
];

export default function Signup() {
  const [mode, setMode] = useState("patient");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [risk, setRisk] = useState([]);

  async function submit(e) {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError(null);
    try {
      if (mode === "patient") {
        await signupPatient({
          name: f.name,
          phone: f.phone,
          password: f.password,
          dob: f.dob,
          sex: f.sex,
          language: f.language,
          village: f.village || null,
          risk_factors: risk,
          bmi: f.bmi ? Number(f.bmi) : null,
        });
      } else {
        await signupDoctor({
          name: f.name,
          email: f.email,
          password: f.password,
          reg_no: f.reg_no,
          facility: f.facility,
          specialty: f.specialty || null,
        });
      }
    } catch (err) {
      setError(err.detail || err.message);
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-paper-line bg-paper-card">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Logo />
          <Link to="/login" className="text-sm font-semibold text-forest-700">
            Sign in
          </Link>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-extrabold tracking-tight">Create an account</h1>

        <div className="mt-6 inline-flex rounded-full bg-paper-card border border-paper-line p-1">
          {[
            ["patient", "I am a patient"],
            ["doctor", "I am a clinician"],
          ].map(([k, l]) => (
            <button
              key={k}
              onClick={() => setMode(k)}
              className={`rounded-full px-5 py-2 text-sm font-semibold transition ${
                mode === k ? "bg-forest-900 text-white" : "text-ink-soft"
              }`}
            >
              {l}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="card p-6 mt-6 space-y-5">
          <div className="grid sm:grid-cols-2 gap-5">
            <div>
              <label className="label">Full name</label>
              <input name="name" className="field" required minLength={2} />
            </div>

            {mode === "patient" ? (
              <div>
                <label className="label">Phone number</label>
                <input
                  name="phone"
                  className="field"
                  required
                  inputMode="numeric"
                  pattern="[0-9]{10,15}"
                  placeholder="10 digits"
                />
              </div>
            ) : (
              <div>
                <label className="label">Work email</label>
                <input name="email" type="email" className="field" required />
              </div>
            )}
          </div>

          {mode === "patient" ? (
            <>
              <div className="grid sm:grid-cols-3 gap-5">
                <div>
                  <label className="label">Date of birth</label>
                  <input name="dob" type="date" className="field" required />
                </div>
                <div>
                  <label className="label">Sex</label>
                  <select name="sex" className="field" required defaultValue="female">
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="label">Language</label>
                  <select name="language" className="field" defaultValue="en">
                    <option value="en">English</option>
                    <option value="hi">हिन्दी</option>
                    <option value="kn">ಕನ್ನಡ</option>
                  </select>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-5">
                <div>
                  <label className="label">Village or town</label>
                  <input name="village" className="field" />
                </div>
                <div>
                  <label className="label">Weight-for-height (BMI, optional)</label>
                  <input name="bmi" type="number" step="0.1" className="field" />
                </div>
              </div>

              <fieldset>
                <legend className="label">Any of these apply to you?</legend>
                <div className="grid sm:grid-cols-2 gap-2">
                  {RISK.map(([code, label]) => {
                    const on = risk.includes(code);
                    return (
                      <button
                        type="button"
                        key={code}
                        onClick={() =>
                          setRisk((r) =>
                            on ? r.filter((x) => x !== code) : [...r, code]
                          )
                        }
                        className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition ${
                          on
                            ? "border-forest-500 bg-forest-50 font-semibold"
                            : "border-paper-line bg-white"
                        }`}
                      >
                        <span
                          className={`grid h-5 w-5 shrink-0 place-items-center rounded-md border text-[11px] ${
                            on
                              ? "border-forest-700 bg-forest-900 text-white"
                              : "border-paper-line"
                          }`}
                        >
                          {on ? "✓" : ""}
                        </span>
                        {label}
                      </button>
                    );
                  })}
                </div>
                <p className="mt-2 text-xs text-ink-faint">
                  AIRA never asks for caste, religion, income or community.
                  Those fields do not exist in the database.
                </p>
              </fieldset>
            </>
          ) : (
            <div className="grid sm:grid-cols-3 gap-5">
              <div>
                <label className="label">Registration no.</label>
                <input name="reg_no" className="field" required minLength={3} />
              </div>
              <div>
                <label className="label">Facility</label>
                <input name="facility" className="field" required minLength={2} />
              </div>
              <div>
                <label className="label">Specialty</label>
                <input name="specialty" className="field" />
              </div>
            </div>
          )}

          <div>
            <label className="label">Password</label>
            <input
              name="password"
              type="password"
              className="field"
              required
              minLength={8}
              autoComplete="new-password"
            />
            <p className="mt-1.5 text-xs text-ink-faint">
              At least 8 characters. Stored with argon2id, never in plain text.
            </p>
          </div>

          {error && (
            <p className="text-sm text-tier-high bg-tier-high/[.07] rounded-xl px-4 py-3">
              {error}
            </p>
          )}

          <button className="btn-primary w-full sm:w-auto" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>
      </main>
    </div>
  );
}
