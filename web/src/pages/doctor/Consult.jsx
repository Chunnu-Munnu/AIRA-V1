import { useEffect, useRef, useState } from "react";
import { post } from "../../lib/api";

const SUGGESTIONS = [
  "What does NG12 say about this presentation?",
  "What should have been ordered by now?",
  "What is the referral threshold here?",
];

/**
 * Ask, clinician view.
 *
 * Same endpoint as the patient's chat, different rendering - and the audience
 * is taken from the authenticated role on the server, not from anything this
 * screen sends. A clinician gets the technical layer: guideline sections,
 * retrieval scores, every verification check, and the model's rejected draft
 * when there was one.
 *
 * That last one matters more than it looks. "Show me what it wanted to say
 * and why you stopped it" is the first question anyone serious asks about a
 * filtered language model, and a system that cannot answer it is asking to be
 * trusted rather than earning it.
 */
export default function Consult({ patientId, patientName }) {
  const [messages, setMessages] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text) {
    const question = (text ?? q).trim();
    if (!question || busy) return;
    setQ("");
    setMessages((m) => [...m, { role: "user", text: question }]);
    setBusy(true);
    try {
      const r = await post("/chat", { question, patient_id: patientId });
      setMessages((m) => [...m, { role: "aira", ...r }]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "aira", answer: e.detail || e.message, error: true, citations: [] },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-white/10 bg-slate-900 p-5">
      <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
        Ask about this patient
      </h2>
      <p className="mt-1.5 text-[12px] text-slate-500">
        Answers come from the retrieved guideline text and this patient's own
        record. No name, phone, code or date reaches the model — it sees an age
        band, a sex, and the trajectory numbers.
      </p>

      <div className="mt-4 space-y-3 max-h-[26rem] overflow-y-auto pr-1">
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[80%] rounded-lg bg-white/10 px-3.5 py-2 text-[13px]">
                {m.text}
              </p>
            </div>
          ) : (
            <Reply key={i} m={m} />
          )
        )}
        {busy && <p className="text-[12px] text-slate-500">Retrieving and checking…</p>}
        <div ref={endRef} />
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 mt-4">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-md bg-white/5 px-2.5 py-1.5 text-[11px] font-semibold text-slate-400 hover:bg-white/10 hover:text-white"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="mt-4 flex gap-2"
      >
        <input
          className="flex-1 rounded-md border border-white/15 bg-slate-850 px-3 py-2 text-[13px]"
          placeholder="Ask a clinical question…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          disabled={busy}
        />
        <button
          className="rounded-md bg-white/10 px-4 py-2 text-[13px] font-semibold hover:bg-white/20 disabled:opacity-40"
          disabled={busy || !q.trim()}
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function Reply({ m }) {
  const [open, setOpen] = useState(false);
  const t = m.trace || {};
  const attempts = t.verification || [];
  const rejected = attempts.find((a) => a.draft);

  return (
    <div className="rounded-lg border border-white/10 bg-slate-850 p-3.5">
      <p className="text-[13px] leading-relaxed whitespace-pre-line">{m.answer}</p>

      {(m.citations?.length > 0 || attempts.length > 0) && (
        <button
          onClick={() => setOpen((o) => !o)}
          className="mt-2.5 text-[11px] font-semibold text-slate-400 hover:text-white"
        >
          {open ? "Hide the working" : "Show the working"}
        </button>
      )}

      {open && (
        <div className="mt-3 space-y-3 border-t border-white/10 pt-3 text-[11px]">
          <div className="flex flex-wrap gap-3 text-slate-500">
            <span>route: {t.route}</span>
            {t.llm?.model_used && <span>model: {t.llm.model_used}</span>}
            {t.llm?.latency_ms != null && <span>{t.llm.latency_ms}ms</span>}
            <span>
              {m.fallback_used ? "guideline text (draft rejected)" : "model, verified"}
            </span>
            {t.llm?.pii_removed?.length > 0 && (
              <span className="text-emerald-400">
                stripped before sending: {t.llm.pii_removed.join(", ")}
              </span>
            )}
          </div>

          {m.citations?.map((c, i) => (
            <div key={i}>
              <p className="font-bold text-emerald-300">
                {c.source}
                {c.section ? ` ${c.section}` : ""}
                <span className="ml-2 font-normal text-slate-500">
                  {c.kind === "quote" ? "verbatim guideline" : "our summary"}
                </span>
              </p>
              <p className="mt-1 border-l border-white/15 pl-3 text-slate-400 leading-relaxed">
                {c.quote}
              </p>
            </div>
          ))}

          {attempts.length > 0 && (
            <div>
              <p className="font-bold text-slate-300">Verification</p>
              {attempts.map((a) => (
                <p key={a.attempt} className="text-slate-500">
                  attempt {a.attempt}: {a.passed ? "passed" : "FAILED"}
                  {a.problems?.length > 0 && ` — ${a.problems.join("; ")}`}
                </p>
              ))}
            </div>
          )}

          {rejected && (
            <details>
              <summary className="cursor-pointer font-semibold text-amber-400">
                What the model tried to say, and we stopped
              </summary>
              <p className="mt-1.5 border-l-2 border-amber-500/40 pl-3 text-slate-400 leading-relaxed">
                {rejected.draft}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
