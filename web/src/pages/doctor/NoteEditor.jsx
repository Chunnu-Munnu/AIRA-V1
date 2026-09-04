import { useCallback, useEffect, useState } from "react";
import { get, post, api } from "../../lib/api";
import { fmtDateTime, pretty } from "../../lib/ui";

const LANGS = { en: "English", hi: "हिन्दी", kn: "ಕನ್ನಡ" };

/**
 * The handover note, drafted then edited.
 *
 * AIRA writes a first draft from what the rules already decided - the same
 * numbers that are on the record, in the patient's own language - and the
 * clinician edits it in the room and releases it. It is on the patient's
 * phone before they reach the door.
 *
 * The two properties this screen is built around:
 *
 *   Nothing is sent that a clinician has not opened. There is no auto-send,
 *   and no "AIRA has messaged your patient" behind anyone's back.
 *
 *   The draft and the released text are both kept. The difference between
 *   them is the only honest measure of whether the drafting is any good, and
 *   the screen shows the clinician that their edits are being counted.
 */
export default function NoteEditor({ patientId, patientLanguage }) {
  const [notes, setNotes] = useState(null);
  const [active, setActive] = useState(null);
  const [text, setText] = useState("");
  const [tests, setTests] = useState([]);
  const [followUp, setFollowUp] = useState(14);
  const [lang, setLang] = useState(patientLanguage || "en");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = useCallback(() => {
    get(`/clinic/patients/${patientId}/notes`).then(setNotes).catch(setErr);
  }, [patientId]);

  useEffect(load, [load]);

  function open(n) {
    setActive(n);
    setText(n.text);
    setTests(n.investigations || []);
    setFollowUp(n.follow_up_days || 14);
    setLang(n.language);
    setErr(null);
  }

  async function draft() {
    setBusy(true);
    setErr(null);
    try {
      open(await post(`/clinic/patients/${patientId}/note/draft`));
      load();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const updated = await api(`/clinic/notes/${active.id}`, {
        method: "PUT",
        body: {
          final_text: text,
          investigations: tests,
          follow_up_days: Number(followUp),
          language: lang,
        },
      });
      setActive(updated);
      load();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  async function release() {
    setBusy(true);
    setErr(null);
    try {
      await save();
      const out = await post(`/clinic/notes/${active.id}/release`);
      setActive(out);
      load();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  const S = "w-full rounded-md border border-white/15 bg-slate-850 px-3 py-2 text-[13px]";
  const L = "block text-[10px] uppercase tracking-[.1em] text-slate-400 font-semibold mb-1.5";
  const released = active?.status === "released";
  const edited = active && text.trim() !== active.draft_text?.trim();

  return (
    <div className="grid lg:grid-cols-[1fr_20rem] gap-4 items-start">
      <section className="rounded-xl border border-white/10 bg-slate-900 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
            Note for the patient
          </h2>
          <button
            onClick={draft}
            disabled={busy}
            className="rounded-md bg-white/10 px-3.5 py-1.5 text-[12px] font-semibold hover:bg-white/20 disabled:opacity-40"
          >
            {busy && !active ? "Drafting…" : "New draft from the record"}
          </button>
        </div>

        {!active ? (
          <p className="mt-4 text-[13px] text-slate-400 leading-relaxed">
            AIRA drafts this from the assessment already on screen — the same
            durations and the same investigations, written in{" "}
            {LANGS[patientLanguage] || "the patient's language"}. Edit anything.
            Nothing reaches the patient until you press Send.
          </p>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span
                className={`rounded px-2 py-0.5 font-bold ${
                  released
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-amber-500/15 text-amber-300"
                }`}
              >
                {released ? "SENT" : "DRAFT"}
              </span>
              <span className="text-slate-500">
                drafted by {active.drafted_by}
                {edited ? " · you have edited it" : ""}
              </span>
              {released && (
                <span className="text-slate-500">
                  · sent {fmtDateTime(active.released_at)}
                </span>
              )}
            </div>

            <textarea
              className={`${S} min-h-[15rem] leading-relaxed`}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={released}
            />

            <div className="grid sm:grid-cols-3 gap-3">
              <div>
                <label className={L}>Language</label>
                <select
                  className={S}
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  disabled={released}
                >
                  {Object.entries(LANGS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={L}>Come back in (days)</label>
                <input
                  type="number"
                  min="1"
                  max="365"
                  className={S}
                  value={followUp}
                  onChange={(e) => setFollowUp(e.target.value)}
                  disabled={released}
                />
              </div>
              <div>
                <label className={L}>Tests ordered</label>
                <input
                  className={S}
                  value={tests.join(", ")}
                  onChange={(e) =>
                    setTests(
                      e.target.value
                        .split(",")
                        .map((t) => t.trim().replace(/\s+/g, "_"))
                        .filter(Boolean)
                    )
                  }
                  disabled={released}
                />
              </div>
            </div>

            {err && <p className="text-[13px] text-red-400">{err}</p>}

            {!released && (
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={release}
                  disabled={busy || text.trim().length < 10}
                  className="rounded-md bg-emerald-500/20 px-5 py-2.5 text-[13px] font-bold text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-40"
                >
                  {busy ? "Sending…" : "Send to the patient"}
                </button>
                <button
                  onClick={save}
                  disabled={busy}
                  className="rounded-md border border-white/15 px-4 py-2.5 text-[13px] font-semibold text-slate-300 hover:bg-white/5"
                >
                  Save draft
                </button>
                <button
                  onClick={() => setText(active.draft_text)}
                  disabled={busy || !edited}
                  className="rounded-md px-4 py-2.5 text-[13px] font-semibold text-slate-400 hover:text-white disabled:opacity-30"
                >
                  Revert to AIRA's draft
                </button>
              </div>
            )}

            {released && (
              <p className="text-[12px] text-slate-400">
                This has been given to the patient and can no longer be changed.
                Write a new note rather than editing what they were told.
              </p>
            )}
          </div>
        )}
      </section>

      <aside className="rounded-xl border border-white/10 bg-slate-900 p-5">
        <h3 className="text-[10px] uppercase tracking-[.12em] text-slate-400 font-semibold">
          Notes for this patient
        </h3>
        {!notes ? (
          <p className="mt-3 text-[12px] text-slate-500">Loading…</p>
        ) : notes.length === 0 ? (
          <p className="mt-3 text-[12px] text-slate-500">None yet.</p>
        ) : (
          <div className="mt-3 space-y-1">
            {notes.map((n) => (
              <button
                key={n.id}
                onClick={() => open(n)}
                className={`w-full text-left rounded-md px-3 py-2.5 text-[12px] transition ${
                  active?.id === n.id ? "bg-white/10" : "hover:bg-white/5"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`font-bold ${
                      n.status === "released" ? "text-emerald-300" : "text-amber-300"
                    }`}
                  >
                    {n.status === "released" ? "SENT" : "DRAFT"}
                  </span>
                  <span className="text-slate-500">{fmtDateTime(n.created_at)}</span>
                </div>
                <p className="mt-1 text-slate-400 line-clamp-2">
                  {n.text.replace(/\n+/g, " ").slice(0, 90)}
                </p>
              </button>
            ))}
          </div>
        )}

        <p className="mt-4 border-t border-white/10 pt-3 text-[11px] leading-relaxed text-slate-500">
          Both versions are kept — AIRA's draft and what you actually sent. The
          difference is how we find out whether the drafting is any good, and it
          is the only way this ever improves.
        </p>
      </aside>
    </div>
  );
}
