import { useCallback, useEffect, useState } from "react";
import { get, getSession, post } from "../../lib/api";
import { useLiveUpdates } from "../../lib/ws";
import { useLang } from "../../lib/lang";
import { ErrorNote, Modal, Spinner } from "../../components/Bits";
import { fmtDateTime } from "../../lib/ui";

/**
 * Consent, the way ABDM defines it.
 *
 * The AIRA code stands in for an ABHA address; the link PIN is the OTP
 * challenge; and what a patient issues here is an artefact - scoped,
 * purpose-bound, time-bound and revocable - not a permanent grant.
 *
 * Three properties are enforced by the server and reflected honestly here:
 *
 *   Knowing the code and the PIN grants NOTHING. It creates a request.
 *   Only the patient's tap issues the artefact.
 *   Revoking kills access on the doctor's very next request, not at logout.
 */
export default function Access() {
  const { t } = useLang();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [pin, setPin] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  const load = useCallback(() => {
    get("/consent/mine").then(setRows).catch(setError);
  }, []);

  useEffect(load, [load]);
  useLiveUpdates((event) => {
    if (event.startsWith("consent.")) load();
  });

  async function openNotice(id) {
    const n = await get(`/consent/${id}/notice`);
    setNotice(n);
    // Recording that the notice was actually shown is evidence of informed
    // consent. It is separate from the decision on purpose.
    post(`/consent/${id}/heard`).catch(() => {});
  }

  /**
   * Read the notice aloud.
   *
   * This is the single most important sentence in the product to get in front
   * of someone who cannot read it: it is the moment they hand over their
   * medical history. So it is the one place voice is not a convenience.
   *
   * Sarvam first, because its Indian-language voices are the reason we chose
   * it. The browser's own speechSynthesis second, because it is free, offline,
   * and on a Kannada handset it is usually installed. If neither works the
   * text is still on screen - voice is added to reading here, never instead
   * of it.
   */
  async function readAloud() {
    if (!notice || speaking) return;
    setSpeaking(true);
    try {
      const r = await post("/voice/speak", {
        text: notice.text,
        language: notice.language || "en",
        cache_key: `consent_notice_${notice.language || "en"}`,
      });
      if (r?.audio_base64) {
        const audio = new Audio("data:audio/wav;base64," + r.audio_base64);
        audio.onended = () => setSpeaking(false);
        audio.onerror = () => setSpeaking(false);
        await audio.play();
        return;
      }
      if (typeof speechSynthesis !== "undefined") {
        const u = new SpeechSynthesisUtterance(notice.text);
        u.lang = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" }[notice.language] || "en-IN";
        u.rate = 0.92; // this is a legal notice, not a news bulletin
        u.onend = () => setSpeaking(false);
        u.onerror = () => setSpeaking(false);
        speechSynthesis.speak(u);
        return;
      }
      setSpeaking(false);
    } catch {
      setSpeaking(false);
    }
  }

  async function decide(id, decision) {
    setBusy(true);
    try {
      await post(`/consent/${id}/decide`, { decision });
      setNotice(null);
      load();
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id) {
    setBusy(true);
    try {
      await post(`/consent/${id}/revoke`);
      load();
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorNote error={error} onRetry={load} />;
  if (!rows) return <Spinner />;

  const pending = rows.filter((r) => r.status === "PENDING");
  const active = rows.filter((r) => r.status === "ACTIVE");
  const past = rows.filter((r) => !["PENDING", "ACTIVE"].includes(r.status));

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-extrabold">
          {t("access_title", "Who can see your record")}
        </h1>
        <p className="text-sm text-ink-soft mt-1">
          {t(
            "access_sub",
            "Nobody, until you say so. You can take it back at any time and it stops working immediately."
          )}
        </p>
      </header>

      {/* ── the code and the one-time PIN ────────────────────────────────── */}
      <section className="card p-6">
        <p className="label">{t("your_aira_code", "Your AIRA code")}</p>
        <p className="font-mono text-xl font-bold tracking-wide">
          {pin?.aira_code || getSession()?.aira_code || rows[0]?.aira_code || "—"}
        </p>
        <p className="mt-2 text-sm text-ink-soft">
          {t(
            "code_hint",
            "Give this to a doctor along with a one-time PIN. The code on its own does nothing."
          )}
        </p>

        {pin ? (
          <div className="mt-4 rounded-xl border-2 border-forest-500 bg-forest-50 p-5 text-center">
            <p className="nums text-4xl font-extrabold tracking-[.3em] text-forest-900">
              {pin.pin}
            </p>
            <p className="mt-2 text-xs text-forest-700 font-semibold">
              {t(
                "pin_valid_for",
                `Valid for ${pin.valid_for_minutes} minutes. Read it out; do not send it in a message.`
              ).replace("{n}", pin.valid_for_minutes)}
            </p>
          </div>
        ) : (
          <button
            className="btn-primary mt-4"
            onClick={() => post("/consent/pin").then(setPin)}
          >
            {t("generate_pin", "Generate a PIN")}
          </button>
        )}
      </section>

      {pending.length > 0 && (
        <section>
          <h2 className="font-bold mb-3">
            {t("waiting_your_answer", "Waiting for your answer")}
          </h2>
          <div className="space-y-3">
            {pending.map((r) => (
              <div key={r.id} className="card p-5 border-forest-500 bg-forest-50">
                <p className="font-semibold">{r.doctor_name}</p>
                <p className="text-sm text-ink-soft">{r.doctor_facility}</p>
                <p className="text-xs text-ink-faint mt-1">
                  {t("asked_at", "asked")} {fmtDateTime(r.requested_at)}
                </p>
                <div className="flex flex-wrap gap-2 mt-4">
                  <button className="btn-primary !py-2 !px-4" onClick={() => openNotice(r.id)}>
                    {t("read_what_they_see", "Read what they will see")}
                  </button>
                  <button
                    className="btn-ghost !py-2 !px-4"
                    disabled={busy}
                    onClick={() => decide(r.id, "deny")}
                  >
                    {t("no_btn", "No")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="font-bold mb-3">{t("doctors_with_access", "Doctors with access")}</h2>
        {active.length === 0 ? (
          <p className="text-sm text-ink-soft card p-5">
            {t("nobody_can_see", "Nobody can see your record right now.")}
          </p>
        ) : (
          <div className="space-y-3">
            {active.map((r) => (
              <div key={r.id} className="card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{r.doctor_name}</p>
                    <p className="text-sm text-ink-soft">{r.doctor_facility}</p>
                  </div>
                  <button
                    className="btn-danger !py-2 !px-4"
                    disabled={busy}
                    onClick={() => revoke(r.id)}
                  >
                    {t("take_it_back", "Take it back")}
                  </button>
                </div>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {r.scope.map((s) => (
                    <span key={s} className="chip bg-paper text-ink-soft">
                      {t(`scope_${s}`, s)}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-ink-faint mt-3">
                  {t("given_on", "Given")} {fmtDateTime(r.granted_at)} ·{" "}
                  {t("expires_on", "expires")} {fmtDateTime(r.expires_at)}
                  {r.read_aloud_at ? ` ${t("read_aloud_at", "· notice was read aloud")}` : ""}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {past.length > 0 && (
        <section>
          <h2 className="font-bold mb-3">{t("past_label", "Past")}</h2>
          <div className="space-y-2">
            {past.map((r) => (
              <div key={r.id} className="card px-5 py-3.5 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">{r.doctor_name}</p>
                  <p className="text-xs text-ink-faint">
                    {fmtDateTime(r.revoked_at || r.requested_at)}
                  </p>
                </div>
                <span className="chip bg-paper text-ink-faint">
                  {t(`cstatus_${r.status}`, r.status)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="text-xs text-ink-faint leading-relaxed border-t border-paper-line pt-5">
        {t(
          "consent_abdm_note",
          "This mirrors the ABDM consent model: a scoped, purpose-bound, time-bound, revocable artefact, with every read written to an append-only audit log."
        )}
      </p>

      <Modal
        open={!!notice}
        onClose={() => setNotice(null)}
        title={t("before_you_decide", "Before you decide")}
      >
        {notice && (
          <>
            <p className="text-[17px] leading-relaxed">{notice.text}</p>
            <ul className="mt-5 space-y-2">
              {notice.scope.map((s) => (
                <li key={s} className="flex gap-2.5 text-sm">
                  <span className="text-forest-500">✓</span>
                  {typeof s === "string" ? s : s.label}
                </li>
              ))}
            </ul>
            <button
              onClick={readAloud}
              disabled={speaking}
              className="mt-5 inline-flex items-center gap-2 rounded-full border border-forest-300 bg-forest-50 px-4 py-2 text-sm font-semibold text-forest-700 disabled:opacity-60"
            >
              <span className={speaking ? "animate-pulse" : ""}>🔊</span>
              {speaking
                ? t("reading_it_out", "Reading it out…")
                : t("read_this_to_me", "Read this to me")}
            </button>

            <p className="mt-4 text-xs text-ink-faint">
              {t(
                "access_ends_after",
                `Access ends automatically after ${notice.days} days, and you can end it sooner from this screen.`
              ).replace("{n}", notice.days)}
            </p>
            <div className="flex gap-2 mt-6">
              <button
                className="btn-primary flex-1"
                disabled={busy}
                onClick={() => decide(notice.consent_id, "allow")}
              >
                {t("yes_let_them", "Yes, let them see it")}
              </button>
              <button
                className="btn-ghost"
                disabled={busy}
                onClick={() => decide(notice.consent_id, "deny")}
              >
                {t("no_btn", "No")}
              </button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
