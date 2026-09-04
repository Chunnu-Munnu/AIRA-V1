import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { fmtDateTime, pretty } from "../../lib/ui";

const TONE = {
  low: "text-amber-400",
  high: "text-amber-400",
  normal: "text-emerald-400",
  reported: "text-slate-400",
};

/**
 * Uploaded reports, clinician view.
 *
 * Three things are on this screen that are not on the patient's version: the
 * reference interval beside every value, the raw text the parser worked from,
 * and an explicit statement of what the parser did NOT do. A clinician is
 * entitled to check the machine's working, and being able to see the source
 * text next to the extracted numbers is what makes that possible in seconds
 * rather than by asking the patient to bring the paper back.
 */
export default function Documents({ patientId }) {
  const [docs, setDocs] = useState(null);
  const [err, setErr] = useState(null);
  const [openRaw, setOpenRaw] = useState(null);

  useEffect(() => {
    get(`/documents/patient/${patientId}`).then(setDocs).catch(setErr);
  }, [patientId]);

  if (err)
    return (
      <p className="text-[13px] text-red-400">{err.detail || err.message}</p>
    );
  if (!docs) return <p className="text-[13px] text-slate-500 py-6">Loading…</p>;
  if (docs.length === 0)
    return (
      <div className="rounded-xl border border-white/10 bg-slate-900 p-8 text-center">
        <p className="font-semibold text-[14px]">No reports uploaded</p>
        <p className="mt-1.5 text-[13px] text-slate-400 max-w-md mx-auto">
          The patient can add a blood count or an imaging report from their
          phone. A report showing a test was actually done also closes the
          investigation gap on the queue.
        </p>
      </div>
    );

  return (
    <div className="space-y-4">
      {docs.map((d) => {
        const findings = d.extracted?.findings || [];
        const abnormal = d.extracted?.abnormal_count || 0;
        return (
          <section
            key={d.id}
            className="rounded-xl border border-white/10 bg-slate-900 overflow-hidden"
          >
            <header className="flex flex-wrap items-start justify-between gap-3 border-b border-white/10 p-4">
              <div>
                <p className="font-semibold text-[14px]">{d.filename}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {fmtDateTime(d.at)} · {d.content_type} · read as{" "}
                  {d.extraction_method}
                  {d.episode_id ? " · linked to an encounter" : ""}
                </p>
              </div>
              {abnormal > 0 && (
                <span className="rounded bg-amber-500/15 px-2 py-1 text-[11px] font-bold text-amber-300">
                  {abnormal} outside reference
                </span>
              )}
            </header>

            {findings.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px] nums min-w-[34rem]">
                  <thead className="bg-slate-850 text-[10px] uppercase tracking-[.1em] text-slate-400 text-left">
                    <tr>
                      <th className="px-4 py-2">Analyte</th>
                      <th className="px-4 py-2 text-right">Value</th>
                      <th className="px-4 py-2">Unit</th>
                      <th className="px-4 py-2 text-right">Reference</th>
                      <th className="px-4 py-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {findings.map((f, i) => (
                      <tr key={i} className="border-t border-white/[.07]">
                        <td className="px-4 py-2 font-semibold">
                          {pretty(f.analyte)}
                        </td>
                        <td className="px-4 py-2 text-right">
                          {f.value ?? f.text_value ?? "—"}
                        </td>
                        <td className="px-4 py-2 text-slate-400">{f.unit || "—"}</td>
                        <td className="px-4 py-2 text-right text-slate-400">
                          {f.reference_low != null
                            ? `${f.reference_low}–${f.reference_high}`
                            : "—"}
                        </td>
                        <td className={`px-4 py-2 font-bold ${TONE[f.status] || ""}`}>
                          {f.status.toUpperCase()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="p-4 text-[13px] text-slate-400">
                {(d.extracted?.notes || []).join(" ") || "Nothing extracted."}
              </p>
            )}

            <div className="p-4 space-y-3 border-t border-white/10">
              {d.summary && (
                <p className="text-[13px] text-slate-300 leading-relaxed">
                  {d.summary}
                </p>
              )}
              {d.extracted?.impression && (
                <div>
                  <p className="text-[10px] uppercase tracking-[.1em] text-slate-400 font-semibold">
                    Impression, as written in the report
                  </p>
                  <p className="mt-1 text-[13px] text-slate-300 border-l-2 border-white/15 pl-3">
                    {d.extracted.impression}
                  </p>
                </div>
              )}

              <div className="flex flex-wrap gap-3 text-[11px]">
                {d.raw_text && (
                  <button
                    onClick={() => setOpenRaw(openRaw === d.id ? null : d.id)}
                    className="font-semibold text-slate-400 hover:text-white"
                  >
                    {openRaw === d.id ? "Hide" : "Show"} the text it read
                  </button>
                )}
                <span className="text-slate-500">
                  verification: {d.verification?.llm_called ? "AI phrasing " : "parser only"}
                  {d.verification?.llm_called &&
                    (d.verification.verified ? "(passed)" : "(rejected, parser text used)")}
                </span>
              </div>

              {openRaw === d.id && (
                <pre className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-400 whitespace-pre-wrap">
                  {d.raw_text}
                </pre>
              )}

              <p className="text-[11px] text-slate-500 leading-relaxed border-t border-white/10 pt-3">
                {d.caveat}
              </p>
            </div>
          </section>
        );
      })}
    </div>
  );
}
