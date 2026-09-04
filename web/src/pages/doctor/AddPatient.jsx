import { useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../../lib/api";
import { fmtDateTime } from "../../lib/ui";

/**
 * Requesting access.
 *
 * The important thing this screen does is fail correctly. A valid code with a
 * wrong PIN and a code that does not exist return the SAME message, so this
 * form cannot be used to discover whether a person is registered.
 *
 * The second important thing is what a success does NOT do: it does not open
 * the record. It creates a request. The patient's phone then decides.
 */
export default function AddPatient() {
  const [code, setCode] = useState("");
  const [pin, setPin] = useState("");
  const [days, setDays] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [granted, setGranted] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await post("/consent/request", {
          aira_code: code.trim().toUpperCase(),
          pin: pin.trim(),
          days: Number(days),
        })
      );
      setCode("");
      setPin("");
    } catch (err) {
      setError(err.detail || err.message);
    } finally {
      setBusy(false);
    }
  }

  const S = "w-full rounded-md border border-white/15 bg-slate-850 px-3.5 py-2.5 text-[13px]";
  const L = "block text-[10px] uppercase tracking-[.1em] text-slate-400 font-semibold mb-1.5";

  return (
    <div className="max-w-3xl space-y-5">
      <Link to="/clinic" className="text-[13px] text-slate-400 hover:text-white">
        ← Queue
      </Link>

      <header>
        <h1 className="text-lg font-bold">Request access to a record</h1>
        <p className="text-[13px] text-slate-400 mt-1">
          Ask the patient for their AIRA code and a one-time PIN generated on
          their own phone.
        </p>
      </header>

      <form onSubmit={submit} className="rounded-xl border border-white/10 bg-slate-900 p-5 space-y-4">
        <div className="grid sm:grid-cols-3 gap-4">
          <div className="sm:col-span-2">
            <label className={L}>AIRA code</label>
            <input
              className={`${S} font-mono uppercase tracking-wider`}
              placeholder="AIRA-XXXX-XXXX"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={L}>One-time PIN</label>
            <input
              className={`${S} font-mono tracking-[.3em]`}
              placeholder="000000"
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              required
            />
          </div>
        </div>

        <div>
          <label className={L}>Access period</label>
          <div className="flex gap-2">
            {[30, 90, 180, 365].map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={`rounded-md px-3.5 py-2 text-[13px] font-semibold ${
                  days === d ? "bg-white/15" : "bg-white/5 text-slate-400"
                }`}
              >
                {d} days
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-500 mt-2">
            The artefact expires by itself. Nothing here grants permanent access.
          </p>
        </div>

        {error && (
          <p className="rounded-md bg-red-500/10 px-3.5 py-2.5 text-[13px] text-red-400">
            {error}
          </p>
        )}

        <button
          disabled={busy}
          className="rounded-md bg-white/10 px-5 py-2.5 text-[13px] font-bold hover:bg-white/20 disabled:opacity-40"
        >
          {busy ? "Sending…" : "Send request"}
        </button>
      </form>

      {result && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/[.06] p-5">
          <p className="font-bold text-emerald-300">Request sent — status {result.status}</p>
          <p className="text-[13px] text-slate-300 mt-1.5 leading-relaxed">
            {result.patient_name} now sees this on their phone. They will hear
            what you are asking for read aloud in their own language, and then
            decide. You have no access until they do.
          </p>
          <p className="text-[11px] text-slate-500 mt-2 font-mono">
            {result.id} · requested {fmtDateTime(result.requested_at)}
          </p>
        </div>
      )}

      <div className="rounded-xl border border-white/10 bg-slate-900 p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
            Your consent artefacts
          </h2>
          <button
            onClick={() => get("/consent/granted").then(setGranted)}
            className="text-[12px] font-semibold text-slate-400 hover:text-white"
          >
            Refresh
          </button>
        </div>

        {!granted ? (
          <p className="text-[13px] text-slate-500 mt-3">
            Load them to see scope, expiry and revocations.
          </p>
        ) : granted.length === 0 ? (
          <p className="text-[13px] text-slate-500 mt-3">Nothing yet.</p>
        ) : (
          <div className="mt-3 divide-y divide-white/[.07]">
            {granted.map((g) => (
              <div key={g.id} className="py-2.5 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[13px] font-semibold">
                    {g.patient_name}{" "}
                    <span className="font-mono text-[11px] text-slate-500">
                      {g.aira_code}
                    </span>
                  </p>
                  <p className="text-[11px] text-slate-500">
                    {g.scope.join(", ")} · expires {fmtDateTime(g.expires_at)}
                  </p>
                </div>
                <span
                  className={`rounded px-2 py-0.5 text-[10px] font-bold ${
                    g.status === "ACTIVE"
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-white/10 text-slate-400"
                  }`}
                >
                  {g.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
