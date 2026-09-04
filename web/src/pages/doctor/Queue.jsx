import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { get } from "../../lib/api";
import { useLiveUpdates } from "../../lib/ws";
import { fmtDateTime, ladder, pretty } from "../../lib/ui";

const STRIPE = { HIGH: "bg-tier-high", MODERATE: "bg-tier-moderate", LOW: "bg-tier-low" };
const TEXT = { HIGH: "text-red-400", MODERATE: "text-amber-400", LOW: "text-emerald-400" };

/**
 * The queue is sorted by CONCERN, never by name, date or arrival.
 *
 * Sorting is: tier, then ladder level, then how far past the safe window the
 * anchor symptom is. That ordering is a clinical statement - the person who
 * has been stuck longest with the least done for them appears first - and it
 * is the reason this screen is not just a patient list.
 */
export default function Queue() {
  const [q, setQ] = useState(null);
  const [error, setError] = useState(null);
  const [live, setLive] = useState(false);
  const nav = useNavigate();

  const load = useCallback(() => {
    get("/clinic/queue").then(setQ).catch(setError);
  }, []);

  useEffect(load, [load]);
  useLiveUpdates((event) => {
    if (event === "patient.updated" || event.startsWith("consent.")) {
      setLive(true);
      load();
      setTimeout(() => setLive(false), 1800);
    }
  });

  if (error)
    return <p className="text-red-400 text-sm">{error.detail || error.message}</p>;
  if (!q) return <p className="text-slate-500 text-sm py-16">Loading queue…</p>;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-bold">Patient queue</h1>
          <p className="text-[13px] text-slate-400 mt-0.5">
            Sorted by concern, not by name. {q.count} with live consent ·{" "}
            <span className="text-red-400 font-semibold">{q.high} high</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider ${
              live ? "text-emerald-400" : "text-slate-500"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live ? "bg-emerald-400 animate-pulse" : "bg-slate-600"
              }`}
            />
            live
          </span>
          <Link
            to="/clinic/add"
            className="rounded-md bg-white/10 px-3.5 py-2 text-[13px] font-semibold hover:bg-white/20"
          >
            + Add patient
          </Link>
        </div>
      </header>

      {q.count === 0 ? (
        <div className="rounded-xl border border-white/10 bg-slate-900 p-12 text-center">
          <p className="font-semibold">No patients have granted you access.</p>
          <p className="text-[13px] text-slate-400 mt-1.5 max-w-md mx-auto">
            You cannot see a record until the patient issues a consent artefact
            from their own phone. Ask them for their AIRA code and a one-time PIN.
          </p>
          <Link
            to="/clinic/add"
            className="inline-block mt-5 rounded-md bg-white/10 px-4 py-2 text-[13px] font-semibold hover:bg-white/20"
          >
            Request access
          </Link>
        </div>
      ) : (
        <div className="rounded-xl border border-white/10 bg-slate-900 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px] min-w-[62rem]">
              <thead className="bg-slate-850 text-[10px] uppercase tracking-[.1em] text-slate-400">
                <tr>
                  <th className="w-1" />
                  <Th className="text-left">Patient</Th>
                  <Th className="text-left">Anchor</Th>
                  <Th>Tier</Th>
                  <Th>Rung</Th>
                  <Th title="Days since onset">Days</Th>
                  <Th title="Days elapsed ÷ safe window for that symptom">Ratio</Th>
                  <Th title="Encounters recorded for this cluster">Visits</Th>
                  <Th title="Investigations ever ordered">Tests</Th>
                  <Th title="Treatment courses that did not resolve it">Failed</Th>
                  <Th className="text-left">Last assessed</Th>
                </tr>
              </thead>
              <tbody className="nums">
                {q.patients.map((p) => (
                  <tr
                    key={p.patient_id}
                    onClick={() => nav(`/clinic/p/${p.patient_id}`)}
                    className="border-t border-white/[.07] hover:bg-white/[.04] cursor-pointer"
                  >
                    <td className={`${STRIPE[p.tier]} w-1 p-0`} />
                    <td className="px-3 py-3">
                      <p className="font-semibold text-white">{p.name}</p>
                      <p className="text-[11px] text-slate-500">
                        {/* "7y M", never "7m" — this queue carries paediatric
                            patients and an age that reads as months is a
                            clinical misread waiting to happen. */}
                        {/* Village is withheld from clinicians by the
                            minimum-necessary policy (api/disclosure.py), so
                            there is no gap to leave a dash in. An empty slot
                            reads as missing data; the field is not missing,
                            it was never sent. */}
                        {[`${p.age}y ${p.sex?.[0]?.toUpperCase() || ""}`.trim(), p.aira_code]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </td>
                    <td className="px-3 py-3 text-slate-300">{pretty(p.anchor)}</td>
                    <td className={`px-3 py-3 text-center font-bold ${TEXT[p.tier]}`}>
                      {p.tier}
                    </td>
                    <td className="px-3 py-3 text-center">
                      <span
                        className="rounded bg-white/10 px-2 py-0.5 text-[11px] font-bold"
                        title={ladder(p.ladder_code).meaning}
                      >
                        L{p.ladder_level}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-center">{p.days_elapsed}</td>
                    <td
                      className={`px-3 py-3 text-center font-semibold ${
                        p.duration_ratio > 1 ? "text-amber-400" : "text-slate-400"
                      }`}
                    >
                      {p.duration_ratio}×
                    </td>
                    <td className="px-3 py-3 text-center">{p.encounters}</td>
                    <td
                      className={`px-3 py-3 text-center font-bold ${
                        p.investigations === 0 && p.encounters > 0
                          ? "text-red-400"
                          : "text-slate-300"
                      }`}
                    >
                      {p.investigations}
                    </td>
                    <td className="px-3 py-3 text-center">{p.failed_treatments}</td>
                    <td className="px-3 py-3 text-[11px] text-slate-500">
                      {fmtDateTime(p.last_assessed)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="text-[11px] text-slate-500 leading-relaxed max-w-3xl">
        A red <b>Tests</b> column means visits happened and nothing was ever
        sent to a lab. That is the pattern AIRA exists to surface — not a
        judgement on any individual consultation, which on its own was almost
        certainly reasonable.
      </p>
    </div>
  );
}

function Th({ children, className = "text-center", title }) {
  return (
    <th className={`px-3 py-2.5 font-semibold ${className}`} title={title}>
      {children}
    </th>
  );
}
