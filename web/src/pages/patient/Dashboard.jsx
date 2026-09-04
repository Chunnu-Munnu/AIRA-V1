import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../../lib/api";
import { fmtDate, ladder, tier as tierOf } from "../../lib/ui";
import { Empty, ErrorNote, Ring, Spinner } from "../../components/Bits";
import { useLang } from "../../lib/lang";
import AddSymptom from "./AddSymptom";
import RecordVisit from "./RecordVisit";
import CheckBack from "./CheckBack";
import NextAction from "./NextAction";

export default function Dashboard() {
  const { lang, synced, t: tr } = useLang();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sheet, setSheet] = useState(null); // 'symptom' | 'visit'
  const [answering, setAnswering] = useState(null);

  const [notes, setNotes] = useState([]);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await get("/me/dashboard"));
    } catch (err) {
      setError(err);
    }
    // A note from a clinician is the highest-value thing on this screen when
    // it exists, so it is fetched alongside rather than hidden behind a tab.
    get("/me/notes").then(setNotes).catch(() => {});
  }, [lang, synced]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorNote error={error} onRetry={load} />;
  if (!data) return <Spinner />;

  const { patient, status, tracked_symptoms, checkbacks_due, screening } = data;
  const t = tierOf(status.tier);
  const rung = ladder(status.ladder_code);

  return (
    <div className="space-y-6">
      {/* ── the headline. One sentence, in the patient's own language. ──── */}
      <section className="card overflow-hidden">
        <div className={`h-1.5 ${t.bg}`} />
        <div className="p-6 sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-ink-faint">
                {greeting(tr)}, <span className="font-semibold text-ink">{patient.name}</span>
              </p>
              <h1 className={`mt-1.5 text-xl font-extrabold ${t.text}`}>{tr(`tier_${status.tier}`, t.label)}</h1>
            </div>
            <span className="chip bg-forest-50 text-forest-700 shrink-0">
              L{status.ladder_level} · {tr(`ladder_${status.ladder_code}`, rung.short)}
            </span>
          </div>

          <p className="mt-4 text-[17px] leading-relaxed">{status.message}</p>

          <p className="mt-4 text-xs text-ink-faint">
            {tr("checked", "Checked")} {fmtDate(status.as_of)} ·{" "}
            {tr(`meaning_${status.ladder_code}`, rung.meaning)}
          </p>

          <Link
            to="/app/ask"
            className="mt-5 inline-flex btn-ghost !py-2 !px-4 text-sm"
          >
            {tr("ask_a_question", "Ask a question")}
          </Link>
        </div>
      </section>

      {/* ── the next step. A risk score is never the last word. ─────────── */}
      <NextAction />

      {/* ── the clinician's own words, if there are any ─────────────────── */}
      {notes.length > 0 && (
        <Link
          to="/app/notes"
          className="card block p-5 hover:border-forest-300 transition"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="label !mb-1">{tr("from_your_doctor", "From your doctor")}</p>
              <p className="font-semibold">{notes[0].doctor_name}</p>
              <p className="mt-1.5 text-sm text-ink-soft line-clamp-2">
                {notes[0].text.replace(/\n+/g, " ")}
              </p>
            </div>
            {notes[0].follow_up_days && (
              <div className="text-right shrink-0">
                <p className="nums text-2xl font-extrabold">{notes[0].follow_up_days}</p>
                <p className="text-[10px] uppercase tracking-wider text-ink-faint">
                  {tr("days_to_return", "days to return")}
                </p>
              </div>
            )}
          </div>
        </Link>
      )}

      {/* ── check-backs. The whole safety net is these two taps. ────────── */}
      {checkbacks_due.length > 0 && (
        <section className="card p-6 border-forest-500 bg-forest-50">
          <p className="label !text-forest-600 !mb-2">{tr("one_question", "One question for you")}</p>
          <p className="text-sm text-ink-soft">
            {checkbacks_due.length === 1
              ? tr("we_said_checkback", "We said we would check back. This is that check.")
              : `${checkbacks_due.length} check-backs are waiting.`}
          </p>
          <div className="mt-4 space-y-2">
            {checkbacks_due.map((cb) => (
              <button
                key={cb.id}
                onClick={() => setAnswering(cb.id)}
                className="btn-primary w-full sm:w-auto"
              >
                {tr("answer_now", "Answer now")}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── what is being watched ───────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold">{tr("watching", "What we are watching")}</h2>
          <div className="flex gap-2">
            <button onClick={() => setSheet("visit")} className="btn-ghost !py-2 !px-4">
              {tr("i_saw_a_doctor", "I saw a doctor")}
            </button>
            <button onClick={() => setSheet("symptom")} className="btn-primary !py-2 !px-4">
              {tr("add_symptom", "+ Symptom")}
            </button>
          </div>
        </div>

        {tracked_symptoms.length === 0 ? (
          <Empty
            title={tr("nothing_tracked", "Nothing is being tracked")}
            body={tr(
              "nothing_tracked_body",
              "Add a symptom when something bothers you. AIRA will remember the date and check back on you."
            )}
          />
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            {tracked_symptoms.map((s) => (
              <SymptomCard key={s.id} s={s} tr={tr} />
            ))}
          </div>
        )}
      </section>

      {/* ── free screening. Deliberately its own section: a screening offer
             must never be mixed into a list of symptom alerts. ─────────── */}
      {screening?.length > 0 && (
        <section>
          <h2 className="font-bold mb-1">{tr("free_checks_title", "Free checks you can have")}</h2>
          <p className="text-sm text-ink-soft mb-3">
            {tr("free_checks_body", "These cost nothing and are not about anything being wrong.")}
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            {screening.slice(0, 2).map((sc) => (
              <div key={sc.id} className="card p-5">
                <div className="flex items-center justify-between">
                  <p className="font-semibold">{sc.name}</p>
                  <span className="chip bg-forest-50 text-forest-700">{tr("free", "Free")}</span>
                </div>
                <p className="mt-2 text-sm text-ink-soft leading-relaxed">{sc.message}</p>
              </div>
            ))}
          </div>
          {screening.length > 2 && (
            <Link
              to="/app/screening"
              className="inline-block mt-3 text-sm font-semibold text-forest-700 underline"
            >
              {tr("see_all", "See all")} {screening.length}
            </Link>
          )}
        </section>
      )}

      <AddSymptom
        open={sheet === "symptom"}
        onClose={() => setSheet(null)}
        onDone={() => {
          setSheet(null);
          load();
        }}
      />
      <RecordVisit
        open={sheet === "visit"}
        onClose={() => setSheet(null)}
        onDone={() => {
          setSheet(null);
          load();
        }}
      />
      <CheckBack
        id={answering}
        onClose={() => setAnswering(null)}
        onDone={() => {
          setAnswering(null);
          load();
        }}
      />
    </div>
  );
}

function SymptomCard({ s, tr }) {
  // The ring is a clock against this symptom's own safe window. It goes amber
  // when the window is spent - it is never red, because a long-running symptom
  // is not a diagnosis and colouring it like one would be a lie.
  const over = s.progress >= 1;
  const colour = s.is_red_flag ? "#a02a20" : over ? "#b4700f" : "#2f7d6b";

  return (
    <div className="card p-5 flex items-center gap-5">
      <Ring value={s.progress} color={colour}>
        <div className="text-center">
          <p className="nums text-lg font-extrabold leading-none">{s.days}</p>
          <p className="text-[9px] uppercase tracking-wider text-ink-faint mt-0.5">
            {tr("days", "days")}
          </p>
        </div>
      </Ring>
      <div className="min-w-0">
        <p className="font-semibold truncate">{s.label}</p>
        <p className="text-xs text-ink-faint mt-1">{tr("since", "Since")} {fmtDate(s.onset_date)}</p>
        <p className={`mt-2 text-xs font-semibold ${over ? "text-tier-moderate" : "text-ink-soft"}`}>
          {s.is_red_flag
            ? tr("see_doctor_about_this", "See a doctor about this one")
            : over
            ? tr("past_window", `Past the usual ${s.safe_window_days} days`).replace(
                "{n}",
                s.safe_window_days
              )
            : tr("days_left", `${s.safe_window_days - s.days} days before we worry`).replace(
                "{n}",
                s.safe_window_days - s.days
              )}
        </p>
      </div>
    </div>
  );
}

function greeting(t) {
  const h = new Date().getHours();
  if (h < 12) return t("good_morning", "Good morning");
  if (h < 17) return t("good_afternoon", "Good afternoon");
  return t("good_evening", "Good evening");
}
