import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { pretty } from "../../lib/ui";

/**
 * Why this tier.
 *
 * The point of this screen is the boundary, not the numbers. A clinician who
 * cannot tell which part of the output came from a published guideline and
 * which came from a statistical model has no basis to disagree with either.
 * So the two are rendered separately and labelled, and the panel states in
 * plain words that the model may only ever raise the tier.
 *
 * The contribution bars are not SHAP approximating a black box after the
 * fact. This is an Explainable Boosting Machine: the per-feature scores ARE
 * the model, and they sum to the log-odds shown at the bottom.
 */
export default function Explain({ id }) {
  const [e, setE] = useState(null);
  const [err, setErr] = useState(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    get(`/clinic/patients/${id}/explain`).then(setE).catch(setErr);
  }, [id]);

  if (err) return <p className="text-red-400 text-sm">{err.detail || err.message}</p>;
  if (!e) return <p className="text-slate-500 text-sm py-8">Loading…</p>;

  const contribs = (e.model_contributions || []).filter(
    (c) => c.feature !== "__baseline__"
  );
  const baseline = (e.model_contributions || []).find(
    (c) => c.feature === "__baseline__"
  );
  const shown = all ? contribs : contribs.slice(0, 8);
  const max = Math.max(...contribs.map((c) => Math.abs(c.contribution)), 0.001);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-white/10 bg-slate-900 p-5">
        <p className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
          Decided by {e.decided_by}
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-slate-300">{e.boundary}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-mono text-slate-500">
          <span className="rounded bg-white/5 px-2 py-1">ruleset {e.ruleset_version}</span>
          {e.model_version && (
            <span className="rounded bg-white/5 px-2 py-1">model {e.model_version}</span>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 items-start">
        {/* ── 1. the deterministic layer ────────────────────────────────── */}
        <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
          <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
            Rules that fired ({e.rules_that_fired.length}) — these set the tier
          </h2>
          <ol className="mt-3 space-y-3">
            {e.rules_that_fired.map((r, i) => (
              <li key={i} className="border-l-2 border-emerald-500/50 pl-3.5">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <code className="text-[11px] font-bold text-emerald-300">
                    {r.rule_id}
                  </code>
                  <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-400">
                    {r.kind}
                  </span>
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-slate-300">
                  {r.statement}
                </p>
                {r.source && (
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[11px] font-semibold text-slate-500 hover:text-slate-300">
                      {r.source}
                      {r.section ? ` ${r.section}` : ""}
                    </summary>
                    {r.quote && (
                      <blockquote className="mt-1.5 border-l border-white/15 pl-3 text-[12px] italic text-slate-400">
                        {r.quote}
                      </blockquote>
                    )}
                  </details>
                )}
              </li>
            ))}
          </ol>
        </section>

        {/* ── 2. the model layer ────────────────────────────────────────── */}
        <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
          <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
            Model contribution — may raise the tier, never lower it
          </h2>

          {e.model_probability == null ? (
            <p className="mt-3 text-[13px] text-slate-400">
              No model score for this record. The rules alone decided it, which
              is a correct and safe outcome, not a degraded one.
            </p>
          ) : (
            <>
              <div className="mt-3 flex items-baseline gap-3">
                <p className="nums text-3xl font-extrabold">
                  {(e.model_probability * 100).toFixed(1)}%
                </p>
                <p className="text-[12px] text-slate-400 leading-snug">
                  estimated risk
                  <br />
                  <span
                    className={
                      e.model_probability >= 0.03 ? "text-amber-400" : "text-slate-500"
                    }
                  >
                    {e.model_probability >= 0.03 ? "above" : "below"} the NG12 3%
                    referral threshold
                  </span>
                </p>
              </div>

              <div className="mt-4 space-y-1.5">
                {shown.map((c) => {
                  const w = (Math.abs(c.contribution) / max) * 100;
                  const up = c.contribution > 0;
                  return (
                    <div key={c.feature} className="flex items-center gap-2 text-[12px]">
                      <span className="w-[11.5rem] shrink-0 truncate text-slate-300" title={c.display}>
                        {c.display}
                      </span>
                      <span className="w-9 shrink-0 text-right nums text-slate-500">
                        {c.value ?? "—"}
                      </span>
                      <span className="flex-1 flex items-center gap-1 min-w-0">
                        <span className="flex-1 flex justify-end">
                          {!up && (
                            <span
                              className="h-2.5 rounded-l bg-emerald-500/60"
                              style={{ width: `${w}%` }}
                            />
                          )}
                        </span>
                        <span className="h-3 w-px bg-white/20" />
                        <span className="flex-1">
                          {up && (
                            <span
                              className="block h-2.5 rounded-r bg-amber-500/70"
                              style={{ width: `${w}%` }}
                            />
                          )}
                        </span>
                      </span>
                      <span className="w-14 shrink-0 text-right nums font-semibold text-slate-400">
                        {c.contribution > 0 ? "+" : ""}
                        {c.contribution.toFixed(3)}
                      </span>
                    </div>
                  );
                })}
              </div>

              {contribs.length > 8 && (
                <button
                  onClick={() => setAll(!all)}
                  className="mt-3 text-[12px] font-semibold text-slate-400 hover:text-white"
                >
                  {all ? "Show fewer" : `Show all ${contribs.length} features`}
                </button>
              )}

              <p className="mt-4 border-t border-white/10 pt-3 text-[11px] leading-relaxed text-slate-500">
                Baseline {baseline?.contribution?.toFixed(3)} log-odds. These
                contributions are not an approximation of what a black box did —
                in an Explainable Boosting Machine they <b>are</b> the model, and
                they sum to the prediction. Monotonic constraints make it
                structurally impossible for risk to fall as smoking years rise,
                or to rise because a test was ordered.
              </p>
            </>
          )}
        </section>
      </div>

      {/* ── 3. the trajectory vector ──────────────────────────────────────── */}
      <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
        <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
          Trajectory vector — the entire input to the Loop Detector
        </h2>
        <div className="mt-3 overflow-x-auto">
          <table className="text-[12px] nums min-w-[38rem] w-full">
            <tbody>
              {Object.entries(e.trajectory || {}).map(([k, v]) => (
                <tr key={k} className="border-t border-white/[.07]">
                  <td className="py-1.5 pr-6 text-slate-400">{pretty(k)}</td>
                  <td className="py-1.5 font-semibold text-right w-24">{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] text-slate-500">
          Seven numbers, not a sequence model. With two to six irregularly
          spaced encounters there is nothing an LSTM could learn that these do
          not already state — and these fit on a card a clinician reads in
          twenty seconds.
        </p>
      </section>
    </div>
  );
}
