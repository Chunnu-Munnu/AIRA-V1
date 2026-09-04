import { useEffect, useState } from "react";
import { get, post } from "../../lib/api";
import { useLang } from "../../lib/lang";
import { Modal, Spinner } from "../../components/Bits";

/**
 * The safety net, and the whole reason AIRA is a longitudinal system rather
 * than a one-shot checker.
 *
 * AIRA said it would check back. This is that check. It is five taps wide and
 * contains no free text, because the answer has to be givable by someone who
 * cannot read comfortably, on a borrowed phone, while doing something else.
 *
 * "Worse" and "Something new started" are the two answers that can move a
 * tier. The rules decide whether they do; this screen only collects the fact.
 */
export default function CheckBack({ id, onClose, onDone }) {
  const { t } = useLang();
  const [cb, setCb] = useState(null);
  const [choice, setChoice] = useState(null);
  const [severity, setSeverity] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setCb(null);
    setChoice(null);
    setError(null);
    if (id) get(`/me/checkbacks/${id}`).then(setCb).catch(setError);
  }, [id]);

  async function answer(response) {
    setBusy(true);
    setError(null);
    try {
      await post(`/me/checkbacks/${id}/answer`, {
        response,
        severity: response === "gone" ? null : Number(severity),
      });
      onDone();
    } catch (err) {
      setError(err.detail || err.message);
      setBusy(false);
    }
  }

  const ORDER = ["same", "better", "worse", "gone", "new_problem"];
  const TONE = {
    worse: "border-tier-high text-tier-high",
    new_problem: "border-tier-moderate text-tier-moderate",
  };

  return (
    <Modal open={!!id} onClose={onClose} title={t("checkin_title", "Checking in")}>
      {!cb ? (
        <Spinner />
      ) : (
        <>
          <p className="text-lg leading-relaxed font-semibold">{cb.question}</p>

          <div className="mt-5 space-y-2">
            {ORDER.filter((k) => cb.options[k]).map((k) => (
              <button
                key={k}
                onClick={() => (k === "gone" ? answer(k) : setChoice(k))}
                disabled={busy}
                className={`w-full text-left rounded-xl border px-4 py-3.5 font-semibold transition ${
                  choice === k
                    ? "border-forest-900 bg-forest-50"
                    : TONE[k] || "border-paper-line text-ink"
                } bg-white hover:border-forest-500`}
              >
                {cb.options[k]}
              </button>
            ))}
          </div>

          {choice && (
            <div className="mt-6 border-t border-paper-line pt-5">
              <label className="label">
                {t("how_bad_now", `How bad is it now? (${severity}/10)`).replace("{n}", severity)}
              </label>
              <input
                type="range"
                min="1"
                max="10"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="w-full accent-forest-700"
              />
              <button
                className="btn-primary w-full mt-4"
                onClick={() => answer(choice)}
                disabled={busy}
              >
                {busy ? t("saving", "Saving…") : t("send", "Send")}
              </button>
            </div>
          )}

          {error && (
            <p className="mt-4 text-sm text-tier-high bg-tier-high/[.07] rounded-xl px-4 py-3">
              {error.detail || error.message}
            </p>
          )}
        </>
      )}
    </Modal>
  );
}
