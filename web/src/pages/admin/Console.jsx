import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, getSession, logout } from "../../lib/api";
import { fmtDateTime, pretty } from "../../lib/ui";
import Logo from "../../components/Logo";

/**
 * The operations console.
 *
 * Note what an administrator can see here: system health, consent counts,
 * ruleset provenance, who read what, and the aggregate investigation-gap rate.
 *
 * Note what they cannot see: a single patient's record. An admin has no
 * clinical read path anywhere in this API. That is not an oversight in the UI;
 * api/deps.py denies it explicitly, because "operations" is the account type
 * most likely to be over-provisioned in a real deployment.
 */
export default function AdminConsole() {
  const nav = useNavigate();
  const [tab, setTab] = useState("overview");
  const [d, setD] = useState({});
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      get("/admin/overview"),
      get("/admin/security-report"),
      get("/admin/doctors"),
      get("/admin/audit"),
      get("/admin/ruleset"),
      get("/voice/status"),
      get("/chat/status"),
    ])
      .then(([overview, security, doctors, audit, ruleset, voice, ai]) =>
        setD({ overview, security, doctors, audit, ruleset, voice, ai })
      )
      .catch(setError);
  }, []);

  if (error)
    return (
      <div className="min-h-screen bg-slate-950 text-red-400 grid place-items-center p-8">
        {error.detail || error.message}
      </div>
    );
  if (!d.overview)
    return (
      <div className="min-h-screen bg-slate-950 text-slate-500 grid place-items-center">
        Loading console…
      </div>
    );

  const o = d.overview;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-900/70 backdrop-blur sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Logo tone="light" size={24} />
            <span className="rounded bg-white/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
              Operations
            </span>
          </div>
          <div className="flex items-center gap-4 text-[13px]">
            <span className="text-slate-400">{getSession()?.display_name}</span>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="font-semibold text-slate-400 hover:text-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-5">
        <div className="rounded-xl border border-amber-500/25 bg-amber-500/[.06] p-4">
          <p className="text-[13px] text-amber-200/90 leading-relaxed">
            <b>Administrators cannot read patient records.</b> There is no
            endpoint for it. Consent artefacts are issued to named clinicians by
            patients, and this account is not in that path.
          </p>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Metric
            label="Patients"
            value={o.users.patients}
            sub={`${o.users.doctors} clinicians`}
          />
          <Metric
            label="Live consents"
            value={o.consent.ACTIVE}
            sub={`${o.consent.PENDING} pending · ${o.consent.REVOKED} revoked`}
          />
          <Metric
            label="Investigation gap"
            value={`${Math.round(o.clinical.investigation_gap_rate * 100)}%`}
            sub={`${o.clinical.episodes_without_investigation} of ${o.clinical.episodes_recorded} encounters`}
            tone="text-amber-400"
          />
          <Metric
            label="At L2 or above"
            value={
              (o.clinical.by_ladder_level["2"] || 0) +
              (o.clinical.by_ladder_level["3"] || 0)
            }
            sub={`${o.clinical.assessments} assessments made`}
            tone="text-red-400"
          />
        </div>

        <nav className="flex flex-wrap gap-1">
          {[
            ["overview", "System"],
            ["ai", "AI layer"],
            ["security", "Security"],
            ["ruleset", "Ruleset"],
            ["doctors", "Clinicians"],
            ["audit", "Audit log"],
          ].map(([k, l]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`rounded-md px-3.5 py-2 text-[13px] font-semibold ${
                tab === k ? "bg-white/10 text-white" : "text-slate-400 hover:text-white"
              }`}
            >
              {l}
            </button>
          ))}
        </nav>

        {tab === "overview" && (
          <div className="grid lg:grid-cols-2 gap-4">
            <Panel title="System">
              <KV rows={Object.entries(o.system)} />
            </Panel>
            <Panel title="Clinical volume">
              <KV
                rows={Object.entries(o.clinical).filter(
                  ([, v]) => typeof v !== "object"
                )}
              />
              <p className="mt-4 text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
                By ladder rung
              </p>
              <KV rows={Object.entries(o.clinical.by_ladder_level)} />
            </Panel>
            <Panel title="Voice / Sarvam credit budget">
              <KV
                rows={[
                  ["mode", d.voice.mode],
                  ["live calls used", `${d.voice.live_calls_used} / ${d.voice.live_calls_budget}`],
                  ["fallback", d.voice.fallback],
                ]}
              />
              <p className="mt-3 text-[11px] text-slate-500 leading-relaxed">
                Development runs in <code>mock</code> mode and makes zero live
                calls. Fixed phrases are rendered to disk once; a hard counter
                caps live calls so a demo cannot exhaust the budget by accident.
              </p>
            </Panel>
            <Panel title="Consent states">
              <KV rows={Object.entries(o.consent)} />
            </Panel>
          </div>
        )}

        {tab === "ai" && (
          <div className="grid lg:grid-cols-2 gap-4">
            <Panel title="Language model — the phrasing layer">
              <KV
                rows={[
                  ["mode", d.ai.llm.mode],
                  ["model", d.ai.llm.model || "not in use"],
                  ["calls used", `${d.ai.llm.calls_used} / ${d.ai.llm.call_budget}`],
                  ["failures", d.ai.llm.failures],
                  ...Object.entries(d.ai.llm.by_task || {}).map(([k, v]) => [
                    `  ${k}`,
                    v,
                  ]),
                  ["fallback", d.ai.llm.fallback],
                ]}
              />
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                The model never decides a tier and never introduces a number.
                When it is unavailable, over budget, or its draft fails
                verification, the answer is composed from the guideline text
                instead — so the chatbot degrading has no clinical consequence.
              </p>
            </Panel>

            <Panel title="Retrieval — what it is allowed to answer from">
              <KV
                rows={[
                  ["backend", d.ai.retrieval.backend],
                  ["passages", d.ai.retrieval.chunks],
                  ["verbatim guideline quotes", d.ai.retrieval.quotes],
                  ["our own summaries", d.ai.retrieval.summaries],
                  ["embedding model", d.ai.retrieval.embedding_model || "none"],
                  [
                    "fusion",
                    `${d.ai.retrieval.weights.dense} dense / ${d.ai.retrieval.weights.lexical} lexical`,
                  ],
                  ["score floor", d.ai.retrieval.min_score],
                  ["corpus fingerprint", d.ai.retrieval.fingerprint],
                ]}
              />
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                A number in an answer may only be supported by a verbatim quote
                or by the patient's own record. Our summaries can explain; they
                cannot be the sole authority for a figure.
              </p>
            </Panel>

            <Panel title="Guarantees enforced in code">
              <ul className="space-y-2 text-[12px] text-slate-300">
                {d.ai.guarantees.map((g) => (
                  <li key={g} className="flex gap-2.5">
                    <span className="text-emerald-400 shrink-0">✓</span>
                    {g}
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] text-slate-500">
                Each one has a test in{" "}
                <code className="font-mono">tests/test_guardrails.py</code> that
                runs offline, with no key and no network.
              </p>
            </Panel>

            <Panel title="Voice">
              <KV
                rows={[
                  ["mode", d.voice.mode],
                  [
                    "live calls used",
                    `${d.voice.live_calls_used} / ${d.voice.live_calls_budget}`,
                  ],
                  ...Object.entries(d.voice.by_endpoint || {}).map(([k, v]) => [
                    `  ${k}`,
                    v,
                  ]),
                  ["fallback", d.voice.fallback],
                ]}
              />
              <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                Hindi and Kannada speech goes to Sarvam only when the patient
                asks for it. Typed Indic text is matched offline against the
                ruleset's own phrasings and costs nothing.
              </p>
            </Panel>
          </div>
        )}

        {tab === "security" && (
          <div className="grid lg:grid-cols-2 gap-4">
            <Panel title="Controls in force">
              <KV
                rows={Object.entries(d.security.controls).map(([k, v]) => [
                  k,
                  Array.isArray(v) ? v.join(", ") : String(v),
                ])}
              />
            </Panel>
            <Panel title={`Denials (last ${d.security.window_days} days)`}>
              <KV rows={Object.entries(d.security.denials_by_action)} />
              <p className="mt-4 text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
                Most active readers
              </p>
              <div className="mt-2 space-y-1 nums text-[12px]">
                {d.security.most_active_readers.map((r) => (
                  <div key={r.doctor_id} className="flex justify-between gap-4">
                    <span className="font-mono text-slate-400 truncate">
                      {r.doctor_id.slice(0, 12)}…
                    </span>
                    <span className="font-semibold">{r.record_reads} reads</span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-slate-500">
                A clinician reading far more records than they have patients is
                the signal this table exists to make visible.
              </p>
            </Panel>
          </div>
        )}

        {tab === "ruleset" && (
          <div className="space-y-4">
            {d.ruleset.needs_clinical_review && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/[.06] p-4">
                <p className="font-bold text-amber-300 text-[13px]">
                  Ruleset {d.ruleset.version} — NOT yet clinically signed off
                </p>
                <p className="mt-1.5 text-[12px] leading-relaxed text-amber-200/80">
                  {d.ruleset.review_note}
                </p>
              </div>
            )}
            <Panel title={`Symptoms (${d.ruleset.symptoms.length})`}>
              <div className="overflow-x-auto">
                <table className="w-full text-[12px] nums min-w-[44rem]">
                  <thead className="text-[10px] uppercase tracking-[.1em] text-slate-500">
                    <tr className="text-left">
                      <th className="py-2">Code</th>
                      <th className="py-2">Cluster</th>
                      <th className="py-2 text-right">Safe window</th>
                      <th className="py-2 text-right">Milestones</th>
                      <th className="py-2">Source</th>
                      <th className="py-2">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.ruleset.symptoms.map((s) => (
                      <tr key={s.code} className="border-t border-white/[.07]">
                        <td className="py-1.5 font-semibold">{s.code}</td>
                        <td className="py-1.5 text-slate-400">{pretty(s.cluster)}</td>
                        <td className="py-1.5 text-right">
                          {s.safe_window_days === 0 ? (
                            <span className="text-red-400 font-bold">red flag</span>
                          ) : (
                            `${s.safe_window_days}d`
                          )}
                        </td>
                        <td className="py-1.5 text-right">{s.milestones?.length ?? 0}</td>
                        <td className="py-1.5 text-slate-400">
                          {s.source} {s.section}
                        </td>
                        <td className="py-1.5">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                              s.confidence === "high"
                                ? "bg-emerald-500/15 text-emerald-300"
                                : "bg-amber-500/15 text-amber-300"
                            }`}
                          >
                            {s.confidence}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        )}

        {tab === "doctors" && (
          <Panel title={`Registered clinicians (${d.doctors.length})`}>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px] min-w-[40rem]">
                <thead className="text-[10px] uppercase tracking-[.1em] text-slate-500 text-left">
                  <tr>
                    <th className="py-2">Name</th>
                    <th className="py-2">Registration</th>
                    <th className="py-2">Facility</th>
                    <th className="py-2">Specialty</th>
                    <th className="py-2 text-right">Patients</th>
                  </tr>
                </thead>
                <tbody>
                  {d.doctors.map((x) => (
                    <tr key={x.user_id} className="border-t border-white/[.07]">
                      <td className="py-2 font-semibold">{x.name}</td>
                      <td className="py-2 font-mono text-slate-400">{x.reg_no}</td>
                      <td className="py-2 text-slate-400">{x.facility}</td>
                      <td className="py-2 text-slate-400">{x.specialty || "—"}</td>
                      <td className="py-2 text-right nums font-semibold">
                        {x.patients_with_active_consent}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        {tab === "audit" && (
          <Panel title="Audit log — append-only">
            <div className="overflow-x-auto">
              <table className="w-full text-[12px] min-w-[46rem]">
                <thead className="text-[10px] uppercase tracking-[.1em] text-slate-500 text-left">
                  <tr>
                    <th className="py-2">When</th>
                    <th className="py-2">Role</th>
                    <th className="py-2">Action</th>
                    <th className="py-2">Outcome</th>
                    <th className="py-2">Consent</th>
                    <th className="py-2">IP</th>
                  </tr>
                </thead>
                <tbody className="nums">
                  {d.audit.map((a) => (
                    <tr key={a.id} className="border-t border-white/[.07]">
                      <td className="py-1.5 text-slate-400 whitespace-nowrap">
                        {fmtDateTime(a.at)}
                      </td>
                      <td className="py-1.5">{a.role}</td>
                      <td className="py-1.5 font-semibold">{a.action}</td>
                      <td
                        className={`py-1.5 ${
                          a.outcome === "ok" ? "text-emerald-400" : "text-red-400"
                        }`}
                      >
                        {a.outcome}
                      </td>
                      <td className="py-1.5 font-mono text-slate-500">
                        {a.consent_id ? a.consent_id.slice(0, 8) : "—"}
                      </td>
                      <td className="py-1.5 font-mono text-slate-500">{a.ip}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[11px] text-slate-500">
              The application database user holds no DELETE grant on this table.
              An audit trail an operator can quietly edit is not an audit trail.
            </p>
          </Panel>
        )}
      </main>
    </div>
  );
}

function Metric({ label, value, sub, tone = "" }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900 p-5">
      <p className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
        {label}
      </p>
      <p className={`nums text-3xl font-extrabold mt-1.5 ${tone}`}>{value}</p>
      <p className="text-[11px] text-slate-500 mt-1">{sub}</p>
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
      <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function KV({ rows }) {
  return (
    <dl className="text-[12px] nums">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-6 border-t border-white/[.07] py-1.5">
          <dt className="text-slate-400">{pretty(k)}</dt>
          <dd className="font-semibold text-right">{String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}
