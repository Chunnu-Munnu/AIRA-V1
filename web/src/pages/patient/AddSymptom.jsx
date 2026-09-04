import { useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "../../lib/api";
import { LanguagePicker, useLang } from "../../lib/lang";
import { Modal, Spinner } from "../../components/Bits";
import { pretty } from "../../lib/ui";

const LANGS = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" };

/**
 * Two ways in, one destination.
 *
 * Ticking is the primary path: the people this is built for are far more
 * reliable at recognising a phrase than at producing one, and a tick cannot
 * be misheard. Speech exists for the person who cannot read the list.
 *
 * Speech recognition runs in the BROWSER, not through Sarvam. Sarvam credits
 * are finite and spending one to hear "cough" - a word the tick list already
 * contains - would be indefensible. The server never sees audio from this
 * screen, only text the patient has read back and confirmed.
 */
export default function AddSymptom({ open, onClose, onDone }) {
  const { t, tc } = useLang();
  const [catalogue, setCatalogue] = useState(null);
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState(null);
  const [days, setDays] = useState(14);
  const [severity, setSeverity] = useState(5);
  const [tab, setTab] = useState("tick");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open && !catalogue) get("/me/symptom-catalogue").then(setCatalogue).catch(setError);
  }, [open, catalogue]);

  useEffect(() => {
    if (!open) {
      setPicked(null);
      setQ("");
      setTab("tick");
      setError(null);
    }
  }, [open]);

  const groups = useMemo(() => {
    if (!catalogue) return [];
    const needle = q.trim().toLowerCase();
    const hits = needle
      ? catalogue.filter(
          (c) =>
            c.label.toLowerCase().includes(needle) ||
            c.phrasing.toLowerCase().includes(needle) ||
            c.code.includes(needle)
        )
      : catalogue;
    const by = new Map();
    for (const c of hits) {
      if (!by.has(c.cluster)) by.set(c.cluster, []);
      by.get(c.cluster).push(c);
    }
    return [...by.entries()];
  }, [catalogue, q]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const onset = new Date();
      onset.setDate(onset.getDate() - Number(days));
      await post("/me/symptoms", {
        code: picked.code,
        onset_date: onset.toISOString().slice(0, 10),
        severity: Number(severity),
        source: tab === "voice" ? "voice" : "text",
      });
      onDone();
    } catch (err) {
      setError(err.detail || err.message);
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={t("as_title", "Add a symptom")} wide>
      {picked ? (
        <Confirm
          picked={picked}
          days={days}
          setDays={setDays}
          severity={severity}
          setSeverity={setSeverity}
          onBack={() => setPicked(null)}
          onSave={save}
          busy={busy}
          error={error}
        />
      ) : (
        <>
          <div className="inline-flex rounded-full bg-paper border border-paper-line p-1 mb-5">
            {[
              ["tick", t("as_tab_tick", "Tick from a list")],
              ["voice", t("as_tab_voice", "Say it or type it")],
            ].map(([k, l]) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold transition ${
                  tab === k ? "bg-forest-900 text-white" : "text-ink-soft"
                }`}
              >
                {l}
              </button>
            ))}
          </div>

          {tab === "tick" ? (
            !catalogue ? (
              <Spinner label={t("as_loading", "Loading symptoms")} />
            ) : (
              <>
                <input
                  className="field"
                  placeholder={t("as_search", "Search — try 'cough' or 'lump'")}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  autoFocus
                />
                <div className="mt-4 space-y-5 max-h-[46vh] overflow-y-auto pr-1">
                  {groups.map(([cluster, items]) => (
                    <div key={cluster}>
                      <p className="label">{tc("cl", cluster)}</p>
                      <div className="grid sm:grid-cols-2 gap-2">
                        {items.map((c) => (
                          <button
                            key={c.code}
                            onClick={() => setPicked(c)}
                            className="text-left rounded-xl border border-paper-line bg-white px-4 py-3 text-sm hover:border-forest-500 hover:bg-forest-50 transition"
                          >
                            <span className="font-semibold block">{c.label}</span>
                            {c.phrasing !== c.label && (
                              <span className="text-xs text-ink-faint">"{c.phrasing}"</span>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                  {groups.length === 0 && (
                    <p className="text-sm text-ink-faint py-6 text-center">
                      {t("as_no_match", `Nothing matches "${q}". Try the other tab and say it in your own words.`).replace(
                        "{q}",
                        q
                      )}
                    </p>
                  )}
                </div>
              </>
            )
          ) : (
            <SpeakOrType onPick={setPicked} setDays={setDays} />
          )}
        </>
      )}
    </Modal>
  );
}

function SpeakOrType({ onPick, setDays }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [listening, setListening] = useState(false);
  const [recording, setRecording] = useState(false);
  // One language for the whole app, set in the header. This panel used to
  // carry its own picker, which meant you could dictate in Kannada into an
  // app rendering Hindi and never notice.
  const { lang, t } = useLang();
  const [busy, setBusy] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState(null);
  const [note, setNote] = useState(null);
  const rec = useRef(null);
  const media = useRef(null);

  const supported =
    typeof window !== "undefined" &&
    (window.SpeechRecognition || window.webkitSpeechRecognition);

  useEffect(() => {
    get("/voice/status").then(setVoiceStatus).catch(() => {});
  }, []);

  function listen() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new Ctor();
    rec.current = r;
    r.lang = LANGS[lang];
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      const said = Array.from(e.results)
        .map((x) => x[0].transcript)
        .join(" ");
      setText(said);
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  }

  /**
   * Sarvam speech-to-text, for Hindi and Kannada.
   *
   * The browser's own recogniser is the default because it is free, and for
   * English it is fine. It is not fine for Kannada on a budget Android
   * handset, and it cannot handle the code-mixing people actually speak -
   * "do hafte se khaansi hai". Sarvam's model is trained on Indian speech,
   * so this button exists for the person the tick list does not reach.
   *
   * It costs a credit, so it is opt-in, labelled, and never the default path.
   */
  async function recordWithSarvam() {
    if (recording) {
      media.current?.stop();
      return;
    }
    setNote(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks = [];
      media.current = mr;
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        setBusy(true);
        try {
          const blob = new Blob(chunks, { type: "audio/webm" });
          const b64 = await new Promise((res) => {
            const fr = new FileReader();
            fr.onload = () => res(String(fr.result).split(",")[1]);
            fr.readAsDataURL(blob);
          });
          const r = await post("/voice/transcribe", {
            audio_base64: b64,
            language: lang,
          });
          if (r.transcript) {
            setText(r.transcript);
            setResult(r);
          } else {
            setNote(t("as_no_speech", "Nothing came back from the speech service. Type it instead, or use the tick list."));
          }
        } catch (err) {
          setNote(err.detail || err.message);
        } finally {
          setBusy(false);
        }
      };
      mr.start();
      setRecording(true);
    } catch {
      setNote(t("as_no_mic", "This device would not let us use the microphone."));
    }
  }

  async function analyse() {
    setBusy(true);
    try {
      setResult(await post("/voice/parse-text", { text, language: lang }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-3">
        <span className="label !mb-0">{t("as_speak_or_type", "Speak or type")}</span>
        <LanguagePicker />
      </div>

      <textarea
        className="field min-h-[110px]"
        placeholder={t(
          "as_textarea",
          "Tell us in your own words — “I have had a cough for three weeks and I am losing weight”"
        )}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <div className="flex flex-wrap gap-2 mt-3">
        {supported && (
          <button
            onClick={listening ? () => rec.current?.stop() : listen}
            className={listening ? "btn-danger" : "btn-ghost"}
          >
            <span className={listening ? "animate-pulse" : ""}>●</span>
            {listening
              ? t("as_listening", "Listening… tap to stop")
              : t("as_speak_instead", "Speak instead")}
          </button>
        )}
        {lang !== "en" && (
          <button
            onClick={recordWithSarvam}
            className={recording ? "btn-danger" : "btn-ghost"}
            disabled={busy}
          >
            <span className={recording ? "animate-pulse" : ""}>●</span>
            {recording
              ? t("as_recording", "Recording… tap to stop")
              : t("as_record_in", `Record in ${lang === "hi" ? "हिन्दी" : "ಕನ್ನಡ"}`)}
          </button>
        )}
        <button onClick={analyse} className="btn-primary" disabled={!text.trim() || busy}>
          {busy ? t("reading", "Reading…") : t("as_what_did_i_say", "What did I say?")}
        </button>
      </div>

      {lang !== "en" && (
        <p className="mt-2 text-xs text-ink-faint">
          {voiceStatus?.mode === "live"
            ? `Sarvam · ${voiceStatus.live_calls_budget - voiceStatus.live_calls_used} left today`
            : t(
                "as_voice_mock",
                "Speech-to-text is in mock mode. Typing in your own language works — AIRA already knows the Hindi and Kannada words for every symptom it tracks."
              )}
        </p>
      )}

      {note && (
        <p className="mt-2 text-xs text-tier-moderate bg-tier-moderate/[.07] rounded-lg px-3 py-2">
          {note}
        </p>
      )}

      {result && (
        <div className="mt-6 border-t border-paper-line pt-5">
          {result.candidates.length === 0 ? (
            <p className="text-sm text-ink-soft">
              {t("as_no_candidates", "We could not match that to anything we track. Try the tick list.")}
            </p>
          ) : (
            <>
              <p className="label">{t("as_is_this", "Is this what you meant?")}</p>
              <div className="space-y-2">
                {result.candidates.map((c) => (
                  <button
                    key={c.code}
                    onClick={() => {
                      if (result.duration_days) setDays(result.duration_days);
                      onPick({ code: c.code, label: c.label || pretty(c.code) });
                    }}
                    className="w-full text-left rounded-xl border border-paper-line bg-white px-4 py-3 hover:border-forest-500 hover:bg-forest-50 transition"
                  >
                    <span className="font-semibold">{c.label || pretty(c.code)}</span>
                    <span className="block text-xs text-ink-faint mt-0.5">
                      {t("as_matched_on", "matched on")} “{c.matched_on}”
                    </span>
                  </button>
                ))}
              </div>
              {result.duration_days && (
                <p
                  className="mt-3 text-sm text-ink-soft"
                  dangerouslySetInnerHTML={{
                    __html: t(
                      "as_also_heard",
                      `We also heard <b>${result.duration_days} days</b>. You can change that next.`
                    ).replace("{n}", result.duration_days),
                  }}
                />
              )}
              <p className="mt-3 text-xs text-ink-faint">{result.note}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Confirm({ picked, days, setDays, severity, setSeverity, onBack, onSave, busy, error }) {
  const { t } = useLang();
  return (
    <div>
      <button onClick={onBack} className="text-sm text-forest-700 font-semibold">
        {t("as_choose_else", "← Choose something else")}
      </button>

      <h3 className="mt-4 text-lg font-extrabold">{picked.label}</h3>
      {picked.phrasing && picked.phrasing !== picked.label && (
        <p className="text-sm text-ink-faint">"{picked.phrasing}"</p>
      )}

      <div className="mt-6">
        <label className="label">{t("as_how_long", "How long has this been going on?")}</label>
        <div className="flex flex-wrap gap-2">
          {[3, 7, 14, 21, 30, 60, 90, 180].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-full px-4 py-2 text-sm font-semibold border transition ${
                Number(days) === d
                  ? "bg-forest-900 text-white border-forest-900"
                  : "bg-white border-paper-line text-ink-soft"
              }`}
            >
              {d < 30
                ? t("as_days", `${d} days`).replace("{n}", d)
                : t("as_months", `${Math.round(d / 30)} months`).replace("{n}", Math.round(d / 30))}
            </button>
          ))}
        </div>
        <input
          type="number"
          min="0"
          max="3650"
          className="field mt-3"
          value={days}
          onChange={(e) => setDays(e.target.value)}
        />
        <p className="mt-1.5 text-xs text-ink-faint">
          {t(
            "as_date_note",
            "The date matters more than anything else you enter. Every rule AIRA applies is a clock started on this day."
          )}
        </p>
      </div>

      <div className="mt-6">
        <label className="label">
          {t("as_how_bad", `How bad is it right now? (${severity}/10)`).replace("{n}", severity)}
        </label>
        <input
          type="range"
          min="1"
          max="10"
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="w-full accent-forest-700"
        />
        <div className="flex justify-between text-xs text-ink-faint">
          <span>{t("as_barely", "Barely notice it")}</span>
          <span>{t("as_worst", "As bad as it gets")}</span>
        </div>
      </div>

      {error && (
        <p className="mt-4 text-sm text-tier-high bg-tier-high/[.07] rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      <button onClick={onSave} className="btn-primary w-full mt-6" disabled={busy}>
        {busy ? t("saving", "Saving…") : t("as_start_tracking", "Start tracking this")}
      </button>
    </div>
  );
}
