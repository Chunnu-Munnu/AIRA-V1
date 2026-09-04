import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Empty, ErrorNote, Spinner, Stat } from "../../components/Bits";
import { fmtDate, ladder, pretty, tier as tierOf } from "../../lib/ui";

/**
 * The Handoff Card.
 *
 * The product's real deliverable. A patient who is not believed the fourth
 * time hands over a single page that states, in numbers and with citations,
 * what has already been tried and what has never been done. It is designed to
 * be printed, screenshotted on a feature phone, or read across a desk in
 * twenty seconds.
 */
export default function Report() {
  const { lang, synced, t, tc } = useLang();
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/me/handoff-card").then(setCard).catch(setError);
  }, [lang, synced]);

  if (error) return <ErrorNote error={error} />;
  if (!card) return <Spinner />;
  if (!card.headline)
    return (
      <Empty
        title={t("card_no_card_title", "No card yet")}
        body={t("card_no_card_body", "Track a symptom first and a card is generated for you.")}
      />
    );

  const tone = tierOf(card.headline.tier);
  const n = card.the_numbers;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4 print:hidden">
        <div>
          <h1 className="text-xl font-extrabold">{t("card_title", "Card for your doctor")}</h1>
          <p className="text-sm text-ink-soft mt-1">
            {t("card_sub", "Show this, or print it. It is one page and it is all facts.")}
          </p>
        </div>
        <button onClick={() => window.print()} className="btn-ghost !py-2 !px-4">
          {t("print", "Print")}
        </button>
      </div>

      <article className="card overflow-hidden">
        <div className={`h-2 ${tone.bg}`} />

        <header className="p-6 border-b border-paper-line">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-extrabold">{card.patient.name}</h2>
              <p className="text-sm text-ink-soft">
                {card.patient.age} · {pretty(card.patient.sex)} · {card.patient.village || "—"}
              </p>
              <p className="font-mono text-xs text-ink-faint mt-1">
                {card.patient.aira_code}
              </p>
            </div>
            <div className="text-right">
              <p className={`text-lg font-extrabold ${tone.text}`}>{tone.clinical}</p>
              <p className="text-xs font-semibold text-ink-soft">
                L{card.headline.ladder.charAt(1)} ·{" "}
                {t(`ladder_${card.headline.ladder}`, ladder(card.headline.ladder).short)}
              </p>
              <p className="text-xs text-ink-faint mt-1">
                {t("card_anchor", "anchor")}: {pretty(card.headline.anchor)}
              </p>
            </div>
          </div>

          {card.patient.risk_factors?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-4">
              {card.patient.risk_factors.map((r) => (
                <span key={r} className="chip bg-paper text-ink-soft">
                  {pretty(r)}
                </span>
              ))}
            </div>
          )}
        </header>

        {/* The numbers. These are the whole argument, and every one of them is
            counted, not inferred. */}
        <section className="p-6 border-b border-paper-line grid grid-cols-2 sm:grid-cols-4 gap-5">
          <Stat
            label={t("card_days", "Days")}
            value={n.days_elapsed}
            sub={t("card_window", `window ${n.safe_window_days}d`).replace("{n}", n.safe_window_days)}
          />
          <Stat
            label={t("card_overdue_by", "Overdue by")}
            value={`${n.duration_ratio}×`}
            tone={n.duration_ratio > 1 ? "text-tier-moderate" : ""}
          />
          <Stat
            label={t("card_doctors_seen", "Doctors seen")}
            value={n.encounters}
            sub={t("card_places", `${n.provider_switches} places`).replace("{n}", n.provider_switches)}
          />
          <Stat
            label={t("card_tests_ordered", "Tests ordered")}
            value={n.investigations_ever_ordered}
            tone={n.investigations_ever_ordered === 0 ? "text-tier-high" : ""}
            sub={t("card_tx_failed", `${n.failed_treatments} treatments failed`).replace(
              "{n}",
              n.failed_treatments
            )}
          />
        </section>

        {card.history?.length > 0 && (
          <section className="p-6 border-b border-paper-line">
            <p className="label">{t("card_already_tried", "What has already been tried")}</p>
            <div className="overflow-x-auto -mx-1 px-1">
              <table className="w-full text-sm min-w-[30rem]">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-ink-faint">
                    <th className="pb-2 font-semibold">{t("col_date", "Date")}</th>
                    <th className="pb-2 font-semibold">{t("col_where", "Where")}</th>
                    <th className="pb-2 font-semibold">{t("col_given", "Given")}</th>
                    <th className="pb-2 font-semibold">{t("col_tested", "Tested")}</th>
                    <th className="pb-2 font-semibold">{t("col_result", "Result")}</th>
                  </tr>
                </thead>
                <tbody className="nums">
                  {card.history.map((h, i) => (
                    <tr key={i} className="border-t border-paper-line">
                      <td className="py-2.5 whitespace-nowrap">{fmtDate(h.date)}</td>
                      <td className="py-2.5">{tc("prov", h.provider)}</td>
                      <td className="py-2.5">{tc("int", h.given)}</td>
                      <td className="py-2.5">
                        {h.investigated === "none" ? (
                          <span className="font-semibold text-tier-high">
                            {t("col_none", "none")}
                          </span>
                        ) : (
                          h.investigated.replace(/_/g, " ")
                        )}
                      </td>
                      <td className="py-2.5">{tc("out", h.outcome || "unknown")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="p-6 border-b border-paper-line">
          <p className="label">{t("card_why", "Why AIRA flagged this")}</p>
          <ul className="space-y-2.5">
            {(card.why_patient || card.why).map((w, i) => (
              <li key={i} className="flex gap-3 text-sm leading-relaxed">
                <span className="text-forest-500 mt-1 shrink-0">▸</span>
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </section>

        {card.suggested_investigations?.length > 0 && (
          <section className="p-6 border-b border-paper-line">
            <p className="label">
              {t("card_guidelines_point", "What the guidelines point to")}
            </p>
            <div className="flex flex-wrap gap-2">
              {(card.suggested_investigation_labels ||
                card.suggested_investigations.map((c) => ({ code: c }))).map((s) => (
                <span
                  key={s.code}
                  className="chip bg-forest-50 text-forest-700 !text-xs !normal-case tracking-normal"
                >
                  {s.label || pretty(s.code)}
                </span>
              ))}
            </div>
            <p className="mt-3 text-xs text-ink-faint">
              {t(
                "card_guidelines_note",
                "Suggestions from published referral criteria. The decision is the clinician's, and AIRA records that it is."
              )}
            </p>
          </section>
        )}

        <footer className="p-6 bg-paper text-xs text-ink-faint space-y-1">
          <p>{card.disclaimer}</p>
          <p className="font-mono">
            ruleset {card.ruleset_version}
            {card.model_version ? ` · model ${card.model_version}` : ""} · {t("generated", "generated")}{" "}
            {fmtDate(card.generated_on)}
          </p>
        </footer>
      </article>
    </div>
  );
}
