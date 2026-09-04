import { useCallback, useEffect, useRef, useState } from "react";
import { api, get } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Empty, ErrorNote, Spinner } from "../../components/Bits";
import { fmtDate, pretty } from "../../lib/ui";

const STATUS_CLS = {
  low: "bg-tier-moderate/10 text-tier-moderate",
  high: "bg-tier-moderate/10 text-tier-moderate",
  normal: "bg-forest-50 text-forest-700",
  reported: "bg-paper text-ink-soft",
};

/**
 * Uploading a report.
 *
 * The screen makes two promises and keeps both. It says what AIRA will read
 * (typed numbers) and what it will not (images, and what any result means),
 * before you upload anything. And an upload that proves a test was actually
 * done is what stops AIRA nagging - so the button is framed as closing a gap,
 * not as feeding a machine.
 */
export default function Reports() {
  const { lang, synced, t } = useLang();
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [latest, setLatest] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(() => {
    get("/documents/mine").then(setDocs).catch(setError);
  }, [lang, synced]);

  useEffect(load, [load]);

  async function upload(file) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setLatest(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("record_as_investigation", "true");
      // fetch() must set its own multipart boundary, so this one call bypasses
      // the JSON helper rather than fighting it.
      const res = await api("/documents", { method: "POST", body: form, raw: true });
      setLatest(res);
      load();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-extrabold">{t("reports_title", "Your reports")}</h1>
        <p className="text-sm text-ink-soft mt-1">
          {t(
            "reports_sub",
            "Add a test result and AIRA stops asking you about a test that has already been done."
          )}
        </p>
      </header>

      <section className="card p-5">
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".txt,.md,.csv,.pdf,image/*"
          onChange={(e) => upload(e.target.files?.[0])}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="btn-primary w-full !py-3.5"
        >
          {busy ? t("reading", "Reading…") : t("add_report", "Add a report")}
        </button>

        <dl className="mt-4 space-y-2 text-xs text-ink-soft">
          <div className="flex gap-2.5">
            <dt className="text-forest-600 font-bold shrink-0">{t("reads_label", "Reads")}</dt>
            <dd>
              {t(
                "reads_body",
                "Typed numbers in a text file or a PDF — blood counts, ESR, sputum and X-ray results."
              )}
            </dd>
          </div>
          <div className="flex gap-2.5">
            <dt className="text-ink-faint font-bold shrink-0">{t("wont_label", "Will not")}</dt>
            <dd>
              {t(
                "wont_body",
                "Read a photograph. A picture of a report is kept for your doctor to look at, but AIRA never guesses at what is in it."
              )}
            </dd>
          </div>
          <div className="flex gap-2.5">
            <dt className="text-ink-faint font-bold shrink-0">{t("never_label", "Never")}</dt>
            <dd>
              {t(
                "never_body",
                "Tell you what a result means. It shows you the usual range and leaves the meaning to your doctor."
              )}
            </dd>
          </div>
        </dl>
      </section>

      {error && <ErrorNote error={error} />}
      {busy && <Spinner label={t("reading", "Reading the report")} />}

      {latest && (
        <section className="card p-5 border-forest-500 bg-forest-50">
          <p className="font-bold">
            {t("read_n_results", `Read ${latest.findings.length} results`).replace(
              "{n}",
              latest.findings.length
            )}
          </p>
          <p className="text-sm text-ink-soft mt-1">{latest.summary}</p>
          {latest.episode_created && (
            <p className="mt-3 chip bg-forest-900 text-white">
              {t("recorded_as_test", "Recorded as a test that was done")}
            </p>
          )}
          <p className="mt-3 text-xs text-ink-faint">{latest.disclaimer}</p>
        </section>
      )}

      {!docs ? (
        <Spinner />
      ) : docs.length === 0 ? (
        <Empty
          title={t("no_reports_title", "No reports yet")}
          body={t(
            "no_reports_body",
            "If you have a blood test or an X-ray report, add it here so your doctor sees it with the rest of your story."
          )}
        />
      ) : (
        <div className="space-y-3">
          {docs.map((d) => (
            <article key={d.id} className="card p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-semibold truncate">{d.filename}</p>
                  <p className="text-xs text-ink-faint mt-0.5">
                    {fmtDate(d.at)} ·{" "}
                    {d.extraction_method === "image"
                      ? t("photo_not_read", "photo, not read")
                      : `${d.findings.length} ${t("values_read", "values read")}`}
                  </p>
                </div>
                {d.abnormal_count > 0 && (
                  <span className="chip bg-tier-moderate/10 text-tier-moderate shrink-0">
                    {d.abnormal_count} {t("outside_range", "outside range")}
                  </span>
                )}
              </div>

              {d.findings.length > 0 && (
                <div className="mt-4 space-y-2">
                  {d.findings.map((f, i) => {
                    const cls = STATUS_CLS[f.status] || STATUS_CLS.reported;
                    return (
                      <div
                        key={i}
                        className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-t border-paper-line pt-2"
                      >
                        <span className="text-sm font-semibold">
                          {pretty(f.analyte)}
                        </span>
                        <span className="nums text-sm">
                          {f.value ?? f.text_value}
                          {f.unit ? ` ${f.unit}` : ""}
                        </span>
                        <span className={`chip ${cls} w-full sm:w-auto`}>
                          {t(`status_${f.status}`, "Recorded")}
                          {f.reference_low != null &&
                            ` · ${t("usual_range", "usual")} ${f.reference_low}–${f.reference_high}`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}

              {d.summary && (
                <p className="mt-4 text-sm text-ink-soft leading-relaxed border-t border-paper-line pt-3">
                  {d.summary}
                </p>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
