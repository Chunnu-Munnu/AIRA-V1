import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Citation, Empty, ErrorNote, Spinner } from "../../components/Bits";

/**
 * Screening lives on its own page, never mixed into the symptom list.
 *
 * A screening offer and a symptom alert mean opposite things. One says
 * "nothing is wrong and we would like to keep it that way"; the other says
 * "something has gone on too long". Putting them in one feed teaches people
 * that a free check-up is a warning, and the free check-up stops happening.
 */
export default function Screening() {
  const { lang, synced, t } = useLang();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/me/dashboard").then(setData).catch(setError);
    // Re-fetch when the language actually lands on the profile, not when
    // the picker is tapped - see lib/lang.jsx.
  }, [lang, synced]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Spinner />;

  const items = data.screening || [];

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-extrabold">
          {t("screening_title", "Free checks you can have")}
        </h1>
        <p className="text-sm text-ink-soft mt-1">
          {t(
            "screening_sub",
            "Run by the government under the National Programme for Non-Communicable Diseases. Nothing here costs money, and none of it means anything is wrong."
          )}
        </p>
      </header>

      {items.length === 0 ? (
        <Empty
          title={t("screening_empty_title", "Nothing due right now")}
          body={t("screening_empty_body", "We will tell you when something is.")}
        />
      ) : (
        <div className="grid sm:grid-cols-2 gap-4">
          {items.map((s) => (
            <article key={s.id} className="card p-5 flex flex-col">
              <div className="flex items-start justify-between gap-3">
                <h2 className="font-bold">{s.name}</h2>
                <span className="chip bg-forest-50 text-forest-700 shrink-0">
                  ₹{s.cost_to_patient}
                </span>
              </div>

              <p className="mt-2.5 text-sm leading-relaxed text-ink-soft flex-1">
                {s.message}
              </p>

              {s.dignity_note && (
                <p className="mt-3 rounded-xl bg-forest-50 px-3.5 py-2.5 text-xs text-forest-700 leading-relaxed">
                  {s.dignity_note}
                </p>
              )}

              <dl className="mt-4 space-y-1.5 text-xs border-t border-paper-line pt-3">
                <Row k={t("scr_test", "Test")} v={s.test} />
                <Row k={t("scr_where", "Where")} v={s.where} />
                <Row k={t("scr_who", "Who does it")} v={s.who_performs} />
                <Row
                  k={t("scr_how_often", "How often")}
                  v={
                    s.interval_months >= 12
                      ? t("scr_every_years", `every ${Math.round(s.interval_months / 12)} years`).replace(
                          "{n}",
                          Math.round(s.interval_months / 12)
                        )
                      : t("scr_every_months", `every ${s.interval_months} months`).replace(
                          "{n}",
                          s.interval_months
                        )
                  }
                />
                {s.interval_shortened_by_risk && (
                  <p className="text-forest-700 font-semibold pt-1">
                    {t("scr_more_often", "More often for you, because of tobacco use.")}
                  </p>
                )}
              </dl>

              <Citation {...(s.citation || {})} />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function Row({ k, v }) {
  if (!v) return null;
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0 text-ink-faint">{k}</dt>
      <dd className="flex-1">{v}</dd>
    </div>
  );
}
