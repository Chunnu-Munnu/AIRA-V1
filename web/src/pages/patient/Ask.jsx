import { useEffect, useRef, useState } from "react";
import { get, post } from "../../lib/api";
import { Spinner } from "../../components/Bits";
import { useLang } from "../../lib/lang";

// The question is SENT in English - the retriever and the verifier both work
// against an English corpus - while the chip shows the reader their own
// language. Translating the chip is presentation; translating the query would
// be changing what gets retrieved.
const SUGGESTIONS = [
  { key: "suggest_wait", en: "Is it safe to wait another month?" },
  { key: "suggest_cost", en: "Will the health centre charge me money?" },
  { key: "suggest_say", en: "What should I say to the doctor?" },
  { key: "suggest_breast", en: "What happens at a breast check?" },
];

/**
 * Ask AIRA.
 *
 * Two things on this screen are deliberate and worth defending.
 *
 * First, every answer carries the guideline it came from, opened with one tap.
 * A health answer without a source is a rumour, and people in this position
 * have already been given plenty of those.
 *
 * Second, when the model's draft fails verification the app says so, in words
 * the patient can read, and shows them the guideline text instead. It does not
 * pretend the AI wrote something good. Being told "this came straight from the
 * guideline" is not a worse experience than being quietly handed a fabrication.
 */
export default function Ask() {
  const [messages, setMessages] = useState([]);
  // The language is the one chosen in the header, not a second dial that
  // can silently disagree with it. Answering in Kannada while the rest of
  // the app is in Hindi is a bug, not a feature.
  const { lang, t } = useLang();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    get("/chat/status").then(setStatus).catch(() => {});
    get("/chat/history?limit=12")
      .then((rows) =>
        setMessages(
          rows.flatMap((r) => [
            { role: "user", text: r.question },
            { role: "aira", ...r },
          ])
        )
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text, shownAs) {
    const question = (text ?? q).trim();
    if (!question || busy) return;
    setQ("");
    setMessages((m) => [...m, { role: "user", text: shownAs || question }]);
    setBusy(true);
    try {
      const r = await post("/chat", { question, language: lang });
      setMessages((m) => [...m, { role: "aira", ...r }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          role: "aira",
          answer: t(
            "chat_error",
            "Something went wrong reaching AIRA. Your record is unaffected — nothing here changes what is being tracked for you."
          ),
          citations: [],
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col min-h-[calc(100dvh-11rem)] sm:min-h-[calc(100dvh-9rem)]">
      <header className="mb-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-extrabold">{t("ask_title", "Ask AIRA")}</h1>
            <p className="text-sm text-ink-soft mt-1">
              {t("ask_subtitle", "It answers only from published health guidelines and your own record.")}
            </p>
          </div>
          {/* No picker here: it lives in the header, on every screen. Two
              controls for one setting is two places for them to disagree. */}
        </div>
      </header>

      <div className="flex-1 space-y-4">
        {messages.length === 0 && (
          <div className="card p-5">
            <p className="text-sm text-ink-soft">
              {t(
                "ask_intro",
                "AIRA will not tell you whether you have cancer — nothing can do that except a test. It can tell you how long something has gone on, what usually happens next, and what is free."
              )}
            </p>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-md bg-forest-900 px-4 py-3 text-sm text-white">
                {m.text}
              </p>
            </div>
          ) : (
            <Reply key={i} m={m} t={t} />
          )
        )}

        {busy && (
          <div className="card p-4 max-w-[85%]">
            <Spinner label={t("checking", "Checking the guidelines")} />
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-2 mt-5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => send(s.en, t(s.key, s.en))}
              className="rounded-full border border-paper-line bg-white px-3.5 py-2 text-xs font-semibold text-ink-soft hover:border-forest-300 hover:text-ink"
            >
              {t(s.key, s.en)}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="sticky bottom-16 sm:bottom-0 mt-5 -mx-5 px-5 py-3 bg-paper/90 backdrop-blur border-t border-paper-line"
      >
        <div className="flex gap-2">
          <input
            className="field flex-1"
            placeholder={t("ask_placeholder", "Ask a question…")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            disabled={busy}
          />
          <button className="btn-primary !px-5" disabled={busy || !q.trim()}>
            {t("send", "Ask")}
          </button>
        </div>
        {status && (
          <p className="mt-2 text-[10px] text-ink-faint">
            {t(
              "chat_footer",
              `${status.retrieval.chunks} guideline passages · ${
                status.llm.mode === "live" ? "AI phrasing on" : "AI phrasing off"
              } · answers are checked against the sources before you see them`
            ).replace("{n}", status.retrieval.chunks)}
          </p>
        )}
      </form>
    </div>
  );
}

function Reply({ m, t }) {
  const [open, setOpen] = useState(false);
  const cites = m.citations || [];

  return (
    <div className="max-w-[92%]">
      <div
        className={`card p-4 ${
          m.refused ? "border-tier-moderate/40 bg-tier-moderate/[.05]" : ""
        }`}
      >
        <p className="text-[15px] leading-relaxed whitespace-pre-line">{m.answer}</p>

        {cites.length > 0 && (
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-3 text-[11px] font-semibold uppercase tracking-[.08em] text-forest-600 hover:text-forest-900"
          >
            {open
              ? t("hide", "Hide")
              : `${t("where_from", "Where this comes from")} (${cites.length})`}
          </button>
        )}

        {open && (
          <div className="mt-3 space-y-2.5 border-t border-paper-line pt-3">
            {cites.map((c, i) => (
              <div key={i}>
                <p className="text-[11px] font-bold uppercase tracking-wide text-forest-600">
                  {c.source}
                  {/* A section like "1.2.4" tells a patient which part of the
                      guideline this is. A section like "symptoms.json#cough"
                      tells them nothing and looks like a leak, because it is
                      our filing system, not theirs. */}
                  {c.section && !c.section.includes(".json") ? ` ${c.section}` : ""}
                </p>
                <p className="mt-1 text-xs text-ink-soft leading-relaxed border-l-2 border-forest-300 pl-3">
                  {c.quote}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {m.fallback_used && !m.refused && (
        <p className="mt-1.5 px-1 text-[11px] text-ink-faint">
          {t(
            "straight_from_guideline",
            "Written straight from the guideline. The AI's version did not pass our checks, so you are reading the source instead."
          )}
        </p>
      )}
    </div>
  );
}
