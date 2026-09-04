import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { useLiveUpdates } from "../../lib/ws";
import { Modal } from "../../components/Bits";
import { fmtDate } from "../../lib/ui";

/**
 * The Next Action card.
 *
 * AIRA never lets a risk score be the last word. Whatever state the patient's
 * care is in - flagged and unseen, seen but incomplete, plan in hand,
 * follow-up due - this card names the state in one sentence and lists the
 * concrete next steps, each with a status the patient controls.
 *
 * Everything clinical on this card (the headline, the step wording, the
 * disclaimer) is rendered server-side in the patient's language by
 * api/care.py. The component only owns the chrome.
 */

const STATUS_STYLE = {
  completed: "bg-forest-500 border-forest-500 text-white",
  in_progress: "bg-amber-100 border-amber-400 text-amber-700",
  overdue: "bg-tier-high/10 border-tier-high text-tier-high",
  pending: "bg-white border-paper-line text-ink-faint",
};

export default function NextAction() {
  const { lang, t } = useLang();
  const nav = useNavigate();
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [respond, setRespond] = useState(false);

  const load = useCallback(() => {
    get("/me/next-action").then(setPlan).catch(() => {});
  }, [lang]);

  useEffect(load, [load]);
  useLiveUpdates((event) => {
    if (["record.updated", "note.released", "treatment.response", "consent.granted"].includes(event))
      load();
  });

  if (!plan || plan.state === "MONITORING") return null;

  async function advance(task) {
    if (!task.patient_actionable || busy) return;
    setBusy(true);
    try {
      setPlan(await post(`/me/care-tasks/${task.id}/advance`));
    } catch {
      /* leave the plan as-is; a failed tap is not a data problem */
    } finally {
      setBusy(false);
    }
  }

  function runCta(key) {
    if (key === "record_response") return setRespond(true);
    if (key === "find_care") return nav("/app/card");
    if (key === "upload_report") return nav("/app/reports");
    if (key === "why_flagged") return nav("/app/card");
    if (key === "view_plan") return nav("/app/notes");
  }

  const { done, total } = plan.progress;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <section className="card overflow-hidden">
      <div className={`h-1.5 ${plan.escalated ? "bg-tier-high" : "bg-forest-500"}`} />
      <div className="p-6 sm:p-7 space-y-5">
        <div>
          <p className="label !mb-1.5 !text-forest-600">{t("next_steps", "Next steps")}</p>
          <h2 className="text-lg font-extrabold leading-snug">{plan.headline}</h2>
          <p className="mt-2 text-sm text-ink-soft leading-relaxed">{plan.subhead}</p>
        </div>

        {plan.escalated && (
          <p className="rounded-xl bg-tier-high/[.07] border border-tier-high/30 px-4 py-3 text-sm text-tier-high">
            {t("escalated_note", "You told us it did not help. We have let your doctor know.")}
          </p>
        )}

        {total > 0 && (
          <div>
            <div className="flex items-center justify-between text-xs font-semibold text-ink-faint mb-1.5">
              <span>
                {done} / {total} {t("of_done", "done")}
              </span>
              <span>{pct}%</span>
            </div>
            <div className="h-1.5 rounded-full bg-paper-line overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${plan.escalated ? "bg-tier-high" : "bg-forest-500"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        <ul className="space-y-2">
          {plan.tasks.map((task) => {
            const style = STATUS_STYLE[task.status] || STATUS_STYLE.pending;
            const label =
              { completed: t("step_done", "Done"), in_progress: t("step_doing", "In progress"),
                overdue: t("step_overdue", "Overdue"), pending: t("step_todo", "To do") }[task.status];
            return (
              <li key={task.id}>
                <button
                  onClick={() => advance(task)}
                  disabled={!task.patient_actionable || busy}
                  className={`w-full flex items-start gap-3 rounded-xl border px-4 py-3 text-left transition ${
                    task.patient_actionable
                      ? "border-paper-line hover:border-forest-300 bg-white"
                      : "border-paper-line bg-paper/60 cursor-default"
                  }`}
                >
                  <span
                    className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[11px] font-bold ${style}`}
                  >
                    {task.status === "completed" ? "✓" : task.status === "overdue" ? "!" : ""}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block text-sm font-semibold ${
                        task.status === "completed" ? "line-through text-ink-faint" : "text-ink"
                      }`}
                    >
                      {task.label}
                    </span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-faint">
                      <span
                        className={
                          task.status === "overdue"
                            ? "font-bold text-tier-high"
                            : task.status === "completed"
                            ? "font-semibold text-forest-600"
                            : ""
                        }
                      >
                        {label}
                      </span>
                      {task.due_date && (
                        <span>
                          · {t("due_on", "by")} {fmtDate(task.due_date)}
                        </span>
                      )}
                      {!task.patient_actionable && task.status !== "completed" && (
                        <span>· {t("step_auto", "completes automatically")}</span>
                      )}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="flex flex-col sm:flex-row gap-2">
          {plan.primary_cta && (
            <button
              onClick={() => runCta(plan.primary_cta.key)}
              className="btn-primary flex-1 sm:flex-none"
            >
              {plan.primary_cta.label}
            </button>
          )}
          {plan.secondary_cta && (
            <button
              onClick={() => runCta(plan.secondary_cta.key)}
              className="btn-ghost flex-1 sm:flex-none"
            >
              {plan.secondary_cta.label}
            </button>
          )}
        </div>

        <p className="text-[11px] text-ink-faint leading-relaxed border-t border-paper-line pt-4">
          {plan.disclaimer}
        </p>
      </div>

      <TreatmentResponseModal
        open={respond}
        onClose={() => setRespond(false)}
        onDone={(p) => {
          setRespond(false);
          setPlan(p);
        }}
      />
    </section>
  );
}

function TreatmentResponseModal({ open, onClose, onDone }) {
  const { t } = useLang();
  const [feeling, setFeeling] = useState(null);
  const [helped, setHelped] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setFeeling(null);
      setHelped(null);
    }
  }, [open]);

  async function submit() {
    if (!feeling || !helped || busy) return;
    setBusy(true);
    try {
      onDone(await post("/me/treatment-response", { feeling, helped }));
    } catch {
      onClose();
    } finally {
      setBusy(false);
    }
  }

  const Choice = ({ set, value, current, children }) => (
    <button
      onClick={() => set(value)}
      className={`rounded-xl border px-4 py-3 text-sm font-semibold transition ${
        current === value
          ? "border-forest-500 bg-forest-50 text-forest-700"
          : "border-paper-line hover:border-forest-300"
      }`}
    >
      {children}
    </button>
  );

  return (
    <Modal open={open} onClose={onClose} title={t("feeling_q", "How are you feeling now?")}>
      <div className="grid grid-cols-3 gap-2">
        <Choice set={setFeeling} value="better" current={feeling}>
          {t("feeling_better", "Better")}
        </Choice>
        <Choice set={setFeeling} value="same" current={feeling}>
          {t("feeling_same", "Same")}
        </Choice>
        <Choice set={setFeeling} value="worse" current={feeling}>
          {t("feeling_worse", "Worse")}
        </Choice>
      </div>

      <p className="mt-5 mb-2 text-sm font-semibold">{t("helped_q", "Did the treatment help?")}</p>
      <div className="grid grid-cols-2 gap-2">
        <Choice set={setHelped} value="yes" current={helped}>
          {t("helped_yes", "Yes")}
        </Choice>
        <Choice set={setHelped} value="partially" current={helped}>
          {t("helped_partially", "Partly")}
        </Choice>
        <Choice set={setHelped} value="no" current={helped}>
          {t("helped_no", "No")}
        </Choice>
        <Choice set={setHelped} value="not_started" current={helped}>
          {t("helped_not_started", "Not started yet")}
        </Choice>
      </div>

      <button
        onClick={submit}
        disabled={!feeling || !helped || busy}
        className="btn-primary w-full mt-6 disabled:opacity-40"
      >
        {busy ? "…" : t("submit", "Submit")}
      </button>
    </Modal>
  );
}
