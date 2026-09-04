import { useEffect, useState } from "react";
import { get, post } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Modal } from "../../components/Bits";
import { INTERVENTION, OUTCOME, PROVIDER } from "../../lib/ui";

/**
 * "I went to a doctor and this is what happened."
 *
 * This is the single most valuable thing a patient can record and the one
 * every other symptom checker throws away. Without the visit, the treatment
 * and the outcome, there is no loop to detect - only a list of complaints.
 *
 * Note what is NOT asked: what the doctor thought it was. A patient cannot
 * reliably report a diagnosis, and a wrong one entered here would poison the
 * record. What they can report accurately is: where they went, what they were
 * given, whether anything was sent to a lab, and whether it helped.
 */
export default function RecordVisit({ open, onClose, onDone }) {
  const { t, tc } = useLang();
  const [clusters, setClusters] = useState([]);
  const [f, setF] = useState(blank());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    setF(blank());
    setError(null);
    get("/me/symptom-catalogue")
      .then((c) => setClusters([...new Set(c.map((x) => x.cluster))]))
      .catch(() => setClusters([]));
  }, [open]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await post("/me/episodes", {
        cluster_id: f.cluster_id,
        encounter_date: f.encounter_date,
        provider_type: f.provider_type,
        intervention_class: f.intervention_class,
        investigation_ordered: f.tested ? f.investigation_ordered || "test_ordered" : "none",
        outcome_at_followup: f.outcome_at_followup || null,
      });
      onDone();
    } catch (err) {
      setError(err.detail || err.message);
      setBusy(false);
    }
  }

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <Modal open={open} onClose={onClose} title={t("rv_title", "Record a doctor visit")}>
      <div className="space-y-5">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="label">{t("rv_when", "When did you go?")}</label>
            <input
              type="date"
              className="field"
              max={new Date().toISOString().slice(0, 10)}
              value={f.encounter_date}
              onChange={set("encounter_date")}
            />
          </div>
          <div>
            <label className="label">{t("rv_about", "What was it about?")}</label>
            <select className="field" value={f.cluster_id} onChange={set("cluster_id")}>
              {clusters.map((c) => (
                <option key={c} value={c}>
                  {tc("cl", c)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="label">{t("rv_where", "Where did you go?")}</label>
          <div className="grid grid-cols-2 gap-2">
            {Object.keys(PROVIDER).map((k) => (
              <Tick
                key={k}
                on={f.provider_type === k}
                onClick={() => setF({ ...f, provider_type: k })}
              >
                {tc("prov", k)}
              </Tick>
            ))}
          </div>
        </div>

        <div>
          <label className="label">{t("rv_given", "What were you given?")}</label>
          <div className="grid grid-cols-2 gap-2">
            {Object.keys(INTERVENTION).map((k) => (
              <Tick
                key={k}
                on={f.intervention_class === k}
                onClick={() => setF({ ...f, intervention_class: k })}
              >
                {tc("int", k)}
              </Tick>
            ))}
          </div>
        </div>

        {/* This one question is the hinge the whole Loop Detector turns on. */}
        <div className="rounded-xl border border-forest-300 bg-forest-50 p-4">
          <label className="label !text-forest-600">
            {t("rv_tested_q", "Did anyone send a sample, do a scan, or take an X-ray?")}
          </label>
          <div className="grid grid-cols-2 gap-2">
            <Tick on={f.tested === false} onClick={() => setF({ ...f, tested: false })}>
              {t("rv_no_just_med", "No, just medicine")}
            </Tick>
            <Tick on={f.tested === true} onClick={() => setF({ ...f, tested: true })}>
              {t("rv_yes_test", "Yes, a test was done")}
            </Tick>
          </div>
          {f.tested && (
            <input
              className="field mt-3"
              placeholder={t("rv_which_test", "Which test, if you remember (e.g. chest x-ray)")}
              value={f.investigation_ordered}
              onChange={set("investigation_ordered")}
            />
          )}
          <p className="mt-2 text-xs text-forest-700">
            {t(
              "rv_test_note",
              "A test that was actually done stops AIRA nagging you. That is the point — it is not counting visits, it is counting unanswered questions."
            )}
          </p>
        </div>

        <div>
          <label className="label">{t("rv_did_help", "Did it help?")}</label>
          <div className="grid grid-cols-2 gap-2">
            {Object.keys(OUTCOME).map((k) => (
              <Tick
                key={k}
                on={f.outcome_at_followup === k}
                onClick={() => setF({ ...f, outcome_at_followup: k })}
              >
                {tc("out", k)}
              </Tick>
            ))}
          </div>
        </div>

        {error && (
          <p className="text-sm text-tier-high bg-tier-high/[.07] rounded-xl px-4 py-3">
            {error}
          </p>
        )}

        <button className="btn-primary w-full" onClick={save} disabled={busy}>
          {busy ? t("saving", "Saving…") : t("rv_save", "Save this visit")}
        </button>
      </div>
    </Modal>
  );
}

function Tick({ on, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-3 text-left text-sm transition ${
        on ? "border-forest-500 bg-white font-semibold" : "border-paper-line bg-white text-ink-soft"
      }`}
    >
      <span
        className={`grid h-4.5 w-4.5 shrink-0 place-items-center rounded-full border text-[10px] ${
          on ? "border-forest-900 bg-forest-900 text-white" : "border-paper-line"
        }`}
        style={{ height: 18, width: 18 }}
      >
        {on ? "✓" : ""}
      </span>
      {children}
    </button>
  );
}

function blank() {
  return {
    cluster_id: "respiratory",
    encounter_date: new Date().toISOString().slice(0, 10),
    provider_type: "phc",
    intervention_class: "none",
    tested: false,
    investigation_ordered: "",
    outcome_at_followup: "unchanged",
  };
}
