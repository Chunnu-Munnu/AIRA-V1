import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Empty, ErrorNote, Spinner } from "../../components/Bits";
import { fmtDate } from "../../lib/ui";

/**
 * The story, in order.
 *
 * This screen exists because it is the argument. Read down it and the loop is
 * obvious: three visits, three prescriptions, no test. Nobody involved could
 * see this - each of them saw one row.
 *
 * The server sends coded fields (provider, given, investigation, outcome);
 * this screen renders them through the same vocabulary the "record a visit"
 * form uses, so the whole app speaks one language at a time.
 */
export default function Timeline() {
  const { lang, synced, t, tc } = useLang();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/me/timeline").then(setData).catch(setError);
  }, [lang, synced]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;

  const events = data.events || [];
  const gaps = events.filter((e) => e.no_investigation).length;

  const KIND = {
    symptom_started: { dot: "bg-forest-500", label: t("tl_symptom_started", "Symptom started") },
    visit: { dot: "bg-slate-700", label: t("tl_visit", "Doctor visit") },
    checkback: { dot: "bg-forest-300", label: t("tl_checkin", "Check-in") },
  };

  function render(e) {
    if (e.kind === "symptom_started") {
      return {
        title: e.symptom_label,
        detail: t("tl_safe_window", `safe window ${e.safe_window_days} days`).replace(
          "{n}",
          e.safe_window_days
        ),
      };
    }
    if (e.kind === "visit") {
      return {
        title: `${KIND.visit.label} · ${tc("prov", e.provider)}`,
        detail: [
          `${t("tl_given", "given")}: ${tc("int", e.given)}`,
          e.investigation !== "none"
            ? `${t("tl_tested", "test")}: ${e.investigation.replace(/_/g, " ")}`
            : null,
          e.outcome !== "unknown" ? `${t("tl_result", "result")}: ${tc("out", e.outcome)}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    }
    return { title: KIND.checkback.label, detail: e.response ? tc("out", e.response) : "" };
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-extrabold">
          {t("timeline_title", "Your story so far")}
        </h1>
        <p className="text-sm text-ink-soft mt-1">
          {t(
            "timeline_sub",
            "Every doctor saw one line of this. AIRA is the only one holding the whole page."
          )}
        </p>
      </header>

      {gaps > 0 && (
        <div className="card p-5 border-tier-moderate/30 bg-tier-moderate/[.05]">
          <p className="font-semibold text-tier-moderate">
            {t("gap_visits", `${gaps} visits where no test was ordered`).replace("{n}", gaps)}
          </p>
          <p className="text-sm text-ink-soft mt-1">
            {t(
              "gap_note",
              "That is not a criticism of any one doctor. Each was making a reasonable call on the day. It is only visible when you line them up."
            )}
          </p>
        </div>
      )}

      {events.length === 0 ? (
        <Empty
          title={t("timeline_empty_title", "Nothing recorded yet")}
          body={t("timeline_empty_body", "Add a symptom and your story starts here.")}
        />
      ) : (
        <ol className="relative border-l-2 border-paper-line ml-3 space-y-6">
          {events.map((e, i) => {
            const k = KIND[e.kind] || KIND.checkback;
            const r = render(e);
            return (
              <li key={i} className="ml-6">
                <span
                  className={`absolute -left-[9px] mt-1.5 h-4 w-4 rounded-full border-4 border-paper ${
                    e.red_flag ? "bg-tier-high" : k.dot
                  }`}
                />
                <div className="card p-4">
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <p className="font-semibold">{r.title}</p>
                    <time className="nums text-xs text-ink-faint shrink-0">
                      {fmtDate(e.date)}
                    </time>
                  </div>
                  {r.detail && <p className="text-sm text-ink-soft mt-1.5">{r.detail}</p>}
                  {e.no_investigation && (
                    <p className="mt-2 chip bg-tier-moderate/10 text-tier-moderate">
                      {t("no_test_ordered", "No test ordered")}
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
