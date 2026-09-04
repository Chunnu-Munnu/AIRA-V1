import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { get, post } from "../../lib/api";
import { INTERVENTION, OUTCOME, PROVIDER, fmtDate, ladder, pretty } from "../../lib/ui";
import Explain from "./Explain";
import Documents from "./Documents";
import NoteEditor from "./NoteEditor";
import Consult from "./Consult";

const TEXT = { HIGH: "text-red-400", MODERATE: "text-amber-400", LOW: "text-emerald-400" };
const STRIPE = { HIGH: "bg-tier-high", MODERATE: "bg-tier-moderate", LOW: "bg-tier-low" };

export default function PatientRecord() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("record");
  const [sheet, setSheet] = useState(null);

  const load = useCallback(() => {
    setError(null);
    get(`/clinic/patients/${id}`).then(setD).catch(setError);
    get(`/clinic/patients/${id}/handoff-card`).then(setCard).catch(() => {});
  }, [id]);

  useEffect(load, [load]);

  if (error)
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-8">
        <p className="font-semibold text-red-400">
          {error.status === 403 ? "Consent is not live for this patient." : "Could not load."}
        </p>
        <p className="text-[13px] text-slate-400 mt-1.5">{error.detail || error.message}</p>
        <Link to="/clinic" className="inline-block mt-4 text-[13px] font-semibold underline">
          ← Back to queue
        </Link>
      </div>
    );
  if (!d) return <p className="text-slate-500 text-sm py-16">Loading record…</p>;

  const a = d.assessment;
  const f = a?.features || {};

  return (
    <div className="space-y-5">
      <Link to="/clinic" className="text-[13px] text-slate-400 hover:text-white">
        ← Queue
      </Link>

      {/* ── header ──────────────────────────────────────────────────────── */}
      <header className="rounded-xl border border-white/10 bg-slate-900 overflow-hidden">
        <div className={`h-1 ${STRIPE[a?.tier] || "bg-slate-700"}`} />
        <div className="p-5 flex flex-wrap items-start justify-between gap-5">
          <div>
            <h1 className="text-lg font-bold">{d.patient.name}</h1>
            <p className="text-[13px] text-slate-400 mt-0.5">
              {d.patient.age} · {pretty(d.patient.sex)} · {d.patient.village || "—"} ·{" "}
              <span className="font-mono">{d.patient.aira_code}</span> ·{" "}
              BMI {d.patient.bmi ?? "—"}
            </p>
            <div className="flex flex-wrap gap-1.5 mt-2.5">
              {d.patient.risk_factors.map((r) => (
                <span
                  key={r}
                  className="rounded bg-white/10 px-2 py-0.5 text-[11px] font-semibold"
                >
                  {pretty(r)}
                </span>
              ))}
            </div>
          </div>

          <div className="text-right">
            <p className={`text-xl font-extrabold ${TEXT[a?.tier] || ""}`}>
              {a?.tier || "—"}
            </p>
            <p className="text-[13px] font-semibold text-slate-300">
              L{a?.ladder_level} · {ladder(a?.ladder_code).short}
            </p>
            <p className="text-[11px] text-slate-500 mt-1 max-w-[15rem]">
              {ladder(a?.ladder_code).meaning}
            </p>
          </div>
        </div>

        {/* The seven numbers. This is the entire input to the trajectory
            model, printed where a clinician can audit it. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 border-t border-white/10 divide-x divide-white/10 nums">
          {[
            ["Days", f.days_elapsed, `window ${f.safe_window_days}d`],
            ["Ratio", `${f.duration_ratio}×`, "vs safe window"],
            ["Visits", f.n_episodes, `${f.provider_switches} providers`],
            ["Tests", f.n_investigations, "ever ordered"],
            ["Failed Rx", f.n_failed_treatments, "did not resolve"],
            ["Severity", f.severity_slope > 0 ? `+${f.severity_slope}` : f.severity_slope, "per 30 days"],
            ["New sx", f.breadth_creep, "since onset"],
          ].map(([k, v, sub], i) => (
            <div key={k} className="px-4 py-3">
              <p className="text-[10px] uppercase tracking-[.1em] text-slate-500">{k}</p>
              <p
                className={`text-lg font-bold mt-0.5 ${
                  (i === 3 && v === 0 && f.n_episodes > 0) || (i === 1 && parseFloat(v) > 1)
                    ? "text-amber-400"
                    : ""
                }`}
              >
                {v ?? "—"}
              </p>
              <p className="text-[10px] text-slate-500">{sub}</p>
            </div>
          ))}
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {[
          ["record", "Record"],
          ["explain", "Why this tier"],
          ["reports", "Reports"],
          ["note", "Note to patient"],
          ["ask", "Ask"],
          ["card", "Handoff card"],
        ].map(([k, l]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`rounded-md px-3.5 py-2 text-[13px] font-semibold transition ${
              tab === k ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            {l}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={() => setSheet("episode")}
          className="rounded-md bg-emerald-500/15 text-emerald-300 px-3.5 py-2 text-[13px] font-semibold hover:bg-emerald-500/25"
        >
          Record what I did
        </button>
        <button
          onClick={() => setSheet("override")}
          className="rounded-md border border-white/15 px-3.5 py-2 text-[13px] font-semibold text-slate-300 hover:bg-white/5"
        >
          Override tier
        </button>
      </div>

      {tab === "record" && <Record d={d} />}
      {tab === "explain" && <Explain id={id} />}
      {tab === "reports" && <Documents patientId={id} />}
      {tab === "note" && (
        <NoteEditor patientId={id} patientLanguage={d.patient.language} />
      )}
      {tab === "ask" && <Consult patientId={id} patientName={d.patient.name} />}
      {tab === "card" && <Card card={card} />}

      <Disclosure consent={d.consent} disclosure={d.patient.disclosure} />

      {sheet === "episode" && (
        <EpisodeSheet
          id={id}
          symptoms={d.symptoms}
          onClose={() => setSheet(null)}
          onDone={() => {
            setSheet(null);
            load();
          }}
        />
      )}
      {sheet === "override" && (
        <OverrideSheet
          id={id}
          current={a?.tier}
          onClose={() => setSheet(null)}
          onDone={() => {
            setSheet(null);
            load();
          }}
        />
      )}
    </div>
  );
}

/**
 * What you can see, and what you cannot.
 *
 * A privacy control nobody can see is indistinguishable from one that does
 * not exist. This panel names every patient field the API withheld and the
 * reason, so a clinician knows exactly what to ask the patient for directly
 * if they genuinely need it - and so nobody has to take a slide's word for it.
 */
function Disclosure({ consent, disclosure }) {
  const [open, setOpen] = useState(false);
  if (!disclosure) return null;

  return (
    <section className="rounded-xl border border-white/10 bg-slate-900 p-4">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-4 text-left"
      >
        <span className="text-[11px] text-slate-400">
          Consent <span className="font-mono">{consent.id?.slice(0, 8)}</span> ·
          scope {consent.scope.join(", ")} · expires {fmtDate(consent.expires_at)} ·{" "}
          <span className="text-slate-300 font-semibold">
            {Object.keys(disclosure.withheld).length} fields withheld
          </span>
        </span>
        <span className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}>
          ⌄
        </span>
      </button>

      {open && (
        <div className="mt-4 grid md:grid-cols-2 gap-5 border-t border-white/10 pt-4">
          <div>
            <p className="text-[10px] uppercase tracking-[.1em] text-emerald-400 font-semibold">
              Shared with you, and why
            </p>
            <dl className="mt-2 space-y-1.5 text-[12px]">
              {Object.entries(disclosure.shared).map(([k, why]) => (
                <div key={k}>
                  <dt className="font-semibold text-slate-200">{pretty(k)}</dt>
                  <dd className="text-slate-500">{why}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[.1em] text-amber-400 font-semibold">
              Withheld, and why
            </p>
            <dl className="mt-2 space-y-1.5 text-[12px]">
              {Object.entries(disclosure.withheld).map(([k, why]) => (
                <div key={k}>
                  <dt className="font-semibold text-slate-200">{pretty(k)}</dt>
                  <dd className="text-slate-500">{why}</dd>
                </div>
              ))}
            </dl>
          </div>
          <p className="md:col-span-2 text-[11px] text-slate-500 leading-relaxed border-t border-white/10 pt-3">
            {disclosure.note} Every read of this record is written to an
            append-only audit log with your identity and this consent id attached.
          </p>
        </div>
      )}
    </section>
  );
}

function Record({ d }) {
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Panel title={`Symptoms (${d.symptoms.length})`}>
        <div className="divide-y divide-white/[.07]">
          {d.symptoms.map((s) => (
            <div key={s.id} className="py-3 flex items-start justify-between gap-4">
              <div>
                <p className="font-semibold text-[13px]">
                  {s.label}
                  {s.is_red_flag && (
                    <span className="ml-2 rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-bold text-red-300">
                      RED FLAG
                    </span>
                  )}
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  from {fmtDate(s.onset_date)} · {s.status}
                </p>
                {s.expected_investigations?.length > 0 && (
                  <p className="text-[11px] text-slate-400 mt-1">
                    expected: {s.expected_investigations.map(pretty).join(", ")}
                  </p>
                )}
              </div>
              <div className="text-right nums shrink-0">
                <p
                  className={`font-bold ${
                    s.days > s.safe_window_days ? "text-amber-400" : "text-slate-300"
                  }`}
                >
                  {s.days}d
                </p>
                <p className="text-[11px] text-slate-500">/ {s.safe_window_days}</p>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title={`Encounters (${d.episodes.length})`}>
        <div className="divide-y divide-white/[.07] nums">
          {d.episodes.map((e) => (
            <div key={e.id} className="py-3">
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-semibold text-[13px]">
                  {PROVIDER[e.provider] || pretty(e.provider)}
                </p>
                <time className="text-[11px] text-slate-500">{fmtDate(e.date)}</time>
              </div>
              <p className="text-[12px] text-slate-400 mt-1">
                {INTERVENTION[e.intervention] || pretty(e.intervention)} ·{" "}
                {OUTCOME[e.outcome] || pretty(e.outcome) || "no follow-up"}
              </p>
              {e.no_investigation ? (
                <p className="mt-1.5 inline-block rounded bg-red-500/15 px-2 py-0.5 text-[10px] font-bold text-red-300">
                  NO INVESTIGATION
                </p>
              ) : (
                <p className="mt-1.5 inline-block rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                  {pretty(e.investigation)}
                </p>
              )}
            </div>
          ))}
          {d.episodes.length === 0 && (
            <p className="py-6 text-[13px] text-slate-500">
              No encounters recorded. This patient has never been seen for this.
            </p>
          )}
        </div>
      </Panel>
    </div>
  );
}

function Card({ card }) {
  if (!card) return <p className="text-slate-500 text-sm py-8">No card available.</p>;
  return (
    <Panel title="Handoff card — what the patient carries">
      <ul className="space-y-2.5 mt-1">
        {card.why.map((w, i) => (
          <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed text-slate-300">
            <span className="text-emerald-400 shrink-0">▸</span>
            {w}
          </li>
        ))}
      </ul>
      <div className="mt-5 border-t border-white/10 pt-4">
        <p className="text-[10px] uppercase tracking-[.1em] text-slate-500 mb-2">
          Suggested by the guidelines
        </p>
        <div className="flex flex-wrap gap-1.5">
          {card.suggested_investigations.map((s) => (
            <span
              key={s}
              className="rounded bg-white/10 px-2 py-1 text-[11px] font-semibold"
            >
              {pretty(s)}
            </span>
          ))}
        </div>
      </div>
      <p className="mt-4 text-[11px] text-slate-500">{card.disclaimer}</p>
    </Panel>
  );
}

function Panel({ title, children }) {
  return (
    <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
      <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
        {title}
      </h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Sheet({ title, onClose, children }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-white/10 bg-slate-900 max-h-[88vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3.5">
          <h2 className="font-bold text-[15px]">{title}</h2>
          <button onClick={onClose} className="text-slate-400 text-xl leading-none">
            ×
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

function EpisodeSheet({ id, symptoms, onClose, onDone }) {
  const clusters = [...new Set(symptoms.map((s) => s.cluster || s.code))];
  const [f, setF] = useState({
    cluster_id: symptoms[0]?.cluster || "respiratory",
    encounter_date: new Date().toISOString().slice(0, 10),
    provider_type: "chc",
    intervention_class: "none",
    investigation_ordered: "",
    outcome_at_followup: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const suggestions = [
    ...new Set(symptoms.flatMap((s) => s.expected_investigations || [])),
  ];

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await post(`/clinic/patients/${id}/episodes`, {
        ...f,
        investigation_ordered: f.investigation_ordered || "none",
        outcome_at_followup: f.outcome_at_followup || null,
      });
      onDone();
    } catch (e) {
      setErr(e.detail || e.message);
      setBusy(false);
    }
  }

  const S = "w-full rounded-md border border-white/15 bg-slate-850 px-3 py-2 text-[13px]";
  const L = "block text-[10px] uppercase tracking-[.1em] text-slate-400 font-semibold mb-1.5";

  return (
    <Sheet title="Record this encounter" onClose={onClose}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={L}>Date</label>
            <input
              type="date"
              className={S}
              value={f.encounter_date}
              onChange={(e) => setF({ ...f, encounter_date: e.target.value })}
            />
          </div>
          <div>
            <label className={L}>Cluster</label>
            <select
              className={S}
              value={f.cluster_id}
              onChange={(e) => setF({ ...f, cluster_id: e.target.value })}
            >
              {(clusters.length ? clusters : ["respiratory"]).map((c) => (
                <option key={c} value={c}>
                  {pretty(c)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={L}>Setting</label>
            <select
              className={S}
              value={f.provider_type}
              onChange={(e) => setF({ ...f, provider_type: e.target.value })}
            >
              {Object.entries(PROVIDER).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={L}>Intervention</label>
            <select
              className={S}
              value={f.intervention_class}
              onChange={(e) => setF({ ...f, intervention_class: e.target.value })}
            >
              {Object.entries(INTERVENTION).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={L}>Investigation ordered</label>
          <input
            className={S}
            placeholder="leave empty if none"
            value={f.investigation_ordered}
            onChange={(e) => setF({ ...f, investigation_ordered: e.target.value })}
          />
          {suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => setF({ ...f, investigation_ordered: s })}
                  className="rounded bg-white/10 px-2 py-1 text-[11px] font-semibold hover:bg-white/20"
                >
                  {pretty(s)}
                </button>
              ))}
            </div>
          )}
          <p className="text-[11px] text-slate-500 mt-2">
            An investigation recorded here clears the loop condition. AIRA stops
            escalating a patient whose clinician did the thing it was asking for.
          </p>
        </div>

        <div>
          <label className={L}>Outcome at follow-up</label>
          <select
            className={S}
            value={f.outcome_at_followup}
            onChange={(e) => setF({ ...f, outcome_at_followup: e.target.value })}
          >
            <option value="">Not yet known</option>
            {Object.entries(OUTCOME).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </div>

        {err && <p className="text-[13px] text-red-400">{err}</p>}

        <button
          onClick={save}
          disabled={busy}
          className="w-full rounded-md bg-emerald-500/20 py-2.5 text-[13px] font-bold text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save encounter"}
        </button>
      </div>
    </Sheet>
  );
}

function OverrideSheet({ id, current, onClose, onDone }) {
  const [tier, setTier] = useState(current || "MODERATE");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      await post(`/clinic/patients/${id}/override`, {
        new_tier: tier,
        rationale,
      });
      onDone();
    } catch (e) {
      setErr(e.detail || e.message);
      setBusy(false);
    }
  }

  return (
    <Sheet title="Override the tier" onClose={onClose}>
      <p className="text-[13px] text-slate-400 leading-relaxed">
        The clinician outranks the system. The override is recorded with your
        identity and your reason, and it is kept — a system nobody can overrule
        gets ignored, and a system whose overrides vanish cannot be improved.
      </p>

      <div className="flex gap-2 mt-4">
        {["LOW", "MODERATE", "HIGH"].map((t) => (
          <button
            key={t}
            onClick={() => setTier(t)}
            className={`flex-1 rounded-md px-3 py-2 text-[13px] font-bold transition ${
              tier === t ? "bg-white/15 text-white" : "bg-white/5 text-slate-400"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <textarea
        className="mt-4 w-full rounded-md border border-white/15 bg-slate-850 px-3 py-2 text-[13px] min-h-[110px]"
        placeholder="Why? Minimum ten characters — e.g. 'Endoscopy today: benign gastric ulcer, H. pylori positive, treated.'"
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
      />

      {err && <p className="text-[13px] text-red-400 mt-2">{err}</p>}

      <button
        onClick={save}
        disabled={busy || rationale.trim().length < 10}
        className="mt-4 w-full rounded-md bg-white/10 py-2.5 text-[13px] font-bold hover:bg-white/20 disabled:opacity-40"
      >
        {busy ? "Saving…" : "Record override"}
      </button>
    </Sheet>
  );
}
