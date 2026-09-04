import { useEffect, useState } from "react";
import { get } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Empty, ErrorNote, Spinner } from "../../components/Bits";
import { fmtDateTime } from "../../lib/ui";

/**
 * What the doctor wrote for you.
 *
 * The whole point is that it is here at all. A patient walks out of a
 * consultation with, on average, about a third of what was said - less if they
 * were frightened, less again if it was in a language they read poorly. This
 * screen is the clinician's own words, in the patient's own language, with the
 * date they were asked to come back.
 */
export default function Notes() {
  const { lang, synced, t } = useLang();
  const [notes, setNotes] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    get("/me/notes").then(setNotes).catch(setError);
  }, [lang, synced]);

  if (error) return <ErrorNote error={error} />;
  if (!notes) return <Spinner />;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-extrabold">{t("notes_title", "From your doctor")}</h1>
        <p className="text-sm text-ink-soft mt-1">
          {t("notes_sub", "Written by the clinician who saw you, in your language.")}
        </p>
      </header>

      {notes.length === 0 ? (
        <Empty
          title={t("notes_empty_title", "Nothing yet")}
          body={t(
            "notes_empty_body",
            "After a visit, your doctor can send you a short note about what happens next. It will appear here."
          )}
        />
      ) : (
        notes.map((n) => (
          <article key={n.id} className="card overflow-hidden">
            <div className="h-1.5 bg-forest-900" />
            <div className="p-5 sm:p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <p className="font-bold">{n.doctor_name}</p>
                  <p className="text-xs text-ink-faint">{n.facility}</p>
                </div>
                <time className="text-xs text-ink-faint">
                  {fmtDateTime(n.released_at)}
                </time>
              </div>

              <p className="mt-5 whitespace-pre-line text-[17px] leading-relaxed">
                {n.text}
              </p>

              {(n.investigations?.length > 0 || n.follow_up_days) && (
                <div className="mt-5 grid gap-4 border-t border-paper-line pt-4 sm:grid-cols-2">
                  {n.investigations?.length > 0 && (
                    <div>
                      <p className="label">{t("tests_to_have", "Tests to have")}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {(n.investigation_labels || n.investigations.map((c) => ({ code: c, label: c }))).map(
                          (iv) => (
                            <span key={iv.code} className="chip bg-forest-50 text-forest-700">
                              {iv.label}
                            </span>
                          )
                        )}
                      </div>
                    </div>
                  )}
                  {n.follow_up_days && (
                    <div>
                      <p className="label">{t("come_back_in", "Come back in")}</p>
                      <p className="nums text-2xl font-extrabold">
                        {n.follow_up_days}{" "}
                        <span className="text-sm font-semibold text-ink-soft">
                          {t("card_days", "days")}
                        </span>
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </article>
        ))
      )}
    </div>
  );
}
