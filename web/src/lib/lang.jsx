/**
 * Language, everywhere, at any time.
 *
 * Three properties this has to satisfy, and each one rules out the obvious
 * shortcut:
 *
 *   1. It has to be changeable mid-session, not only at signup. A shared
 *      phone in a village household is handed between a daughter who reads
 *      English and a mother who reads Kannada. Asking either of them to make
 *      a new account is asking them to abandon the record.
 *
 *   2. It has to reach the SERVER, not just this browser. The symptom list,
 *      the headline, the chatbot answer and the note a clinician drafts are
 *      all rendered server-side in the patient's language. Dr Rao's browser
 *      cannot know that her patient reads Kannada; the profile can.
 *
 *   3. The clinician and admin consoles stay in English on purpose. They are
 *      operated by people trained in English clinical vocabulary, and a
 *      half-translated clinical console is more dangerous than an English one.
 *      This provider is mounted around the patient app only.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { get, getSession, post } from "./api";

export const LANGUAGES = [
  { code: "en", label: "English", short: "EN" },
  { code: "hi", label: "हिन्दी", short: "हि" },
  { code: "kn", label: "ಕನ್ನಡ", short: "ಕ" },
];

const KEY = "aira.lang";

/* ── the chrome ────────────────────────────────────────────────────────────
 * Only the app's own furniture lives here. Clinical content - symptom names,
 * safe windows, the headline, every chatbot answer - is translated on the
 * server against rules/*.json, so that a translation can never disagree with
 * the rule that produced it.
 */
const STRINGS = {
  // navigation
  home: { hi: "होम", kn: "ಮುಖಪುಟ" },
  ask: { hi: "पूछें", kn: "ಕೇಳಿ" },
  reports: { hi: "रिपोर्ट", kn: "ವರದಿ" },
  card: { hi: "कार्ड", kn: "ಕಾರ್ಡ್" },
  more: { hi: "और", kn: "ಇನ್ನಷ್ಟು" },
  from_your_doctor: { hi: "आपके डॉक्टर से", kn: "ನಿಮ್ಮ ವೈದ್ಯರಿಂದ" },
  your_story: { hi: "आपकी कहानी", kn: "ನಿಮ್ಮ ಕಥೆ" },
  free_checks: { hi: "मुफ़्त जाँच", kn: "ಉಚಿತ ತಪಾಸಣೆ" },
  who_can_see: { hi: "आपका रिकॉर्ड कौन देख सकता है", kn: "ನಿಮ್ಮ ದಾಖಲೆ ಯಾರು ನೋಡಬಹುದು" },
  sign_out: { hi: "साइन आउट", kn: "ಸೈನ್ ಔಟ್" },
  language: { hi: "भाषा", kn: "ಭಾಷೆ" },

  // hints under More
  hint_notes: { hi: "जाँच के बाद आपके लिए लिखा गया", kn: "ಭೇಟಿಯ ನಂತರ ನಿಮಗಾಗಿ ಬರೆದದ್ದು" },
  hint_timeline: { hi: "सब कुछ, क्रम में", kn: "ಎಲ್ಲವೂ, ಕ್ರಮವಾಗಿ" },
  hint_screening: { hi: "सरकारी जाँच जो आप करा सकते हैं", kn: "ನೀವು ಪಡೆಯಬಹುದಾದ ಸರ್ಕಾರಿ ತಪಾಸಣೆ" },
  hint_access: { hi: "सहमति, और उसे वापस लेना", kn: "ಸಮ್ಮತಿ, ಮತ್ತು ಅದನ್ನು ಹಿಂಪಡೆಯುವುದು" },

  // dashboard
  good_morning: { hi: "सुप्रभात", kn: "ಶುಭೋದಯ" },
  good_afternoon: { hi: "नमस्कार", kn: "ಶುಭ ಮಧ್ಯಾಹ್ನ" },
  good_evening: { hi: "शुभ संध्या", kn: "ಶುಭ ಸಂಜೆ" },
  show_card: { hi: "यह कार्ड डॉक्टर को दिखाएँ →", kn: "ಈ ಕಾರ್ಡ್ ವೈದ್ಯರಿಗೆ ತೋರಿಸಿ →" },
  ask_a_question: { hi: "एक सवाल पूछें", kn: "ಒಂದು ಪ್ರಶ್ನೆ ಕೇಳಿ" },
  one_question: { hi: "आपके लिए एक सवाल", kn: "ನಿಮಗಾಗಿ ಒಂದು ಪ್ರಶ್ನೆ" },
  answer_now: { hi: "अभी जवाब दें", kn: "ಈಗ ಉತ್ತರಿಸಿ" },
  we_said_checkback: {
    hi: "हमने कहा था कि हम फिर पूछेंगे। यह वही सवाल है।",
    kn: "ನಾವು ಮತ್ತೆ ಕೇಳುತ್ತೇವೆ ಎಂದಿದ್ದೆವು. ಇದು ಆ ಪ್ರಶ್ನೆ.",
  },
  watching: { hi: "हम किस पर नजर रख रहे हैं", kn: "ನಾವು ಏನನ್ನು ಗಮನಿಸುತ್ತಿದ್ದೇವೆ" },
  i_saw_a_doctor: { hi: "मैंने डॉक्टर को दिखाया", kn: "ನಾನು ವೈದ್ಯರನ್ನು ಭೇಟಿಯಾದೆ" },
  add_symptom: { hi: "+ लक्षण", kn: "+ ಲಕ್ಷಣ" },
  nothing_tracked: { hi: "अभी कुछ भी ट्रैक नहीं हो रहा", kn: "ಇನ್ನೂ ಏನನ್ನೂ ಗಮನಿಸುತ್ತಿಲ್ಲ" },
  nothing_tracked_body: {
    hi: "जब कोई परेशानी हो तो लक्षण जोड़ें। AIRA तारीख याद रखेगा और आपसे फिर पूछेगा।",
    kn: "ತೊಂದರೆ ಇದ್ದಾಗ ಲಕ್ಷಣ ಸೇರಿಸಿ. AIRA ದಿನಾಂಕ ನೆನಪಿಟ್ಟು ಮತ್ತೆ ನಿಮ್ಮನ್ನು ಕೇಳುತ್ತದೆ.",
  },
  free_checks_title: { hi: "मुफ़्त जाँच जो आप करा सकते हैं", kn: "ನೀವು ಪಡೆಯಬಹುದಾದ ಉಚಿತ ತಪಾಸಣೆ" },
  free_checks_body: {
    hi: "इनका कोई पैसा नहीं लगता, और इनका मतलब यह नहीं कि कुछ गड़बड़ है।",
    kn: "ಇವು ಉಚಿತ, ಮತ್ತು ಏನೋ ತಪ್ಪಾಗಿದೆ ಎಂದು ಅರ್ಥವಲ್ಲ.",
  },
  free: { hi: "मुफ़्त", kn: "ಉಚಿತ" },
  see_all: { hi: "सभी देखें", kn: "ಎಲ್ಲವನ್ನೂ ನೋಡಿ" },
  days: { hi: "दिन", kn: "ದಿನ" },
  since: { hi: "से", kn: "ಇಂದ" },
  checked: { hi: "जाँचा गया", kn: "ಪರಿಶೀಲಿಸಲಾಗಿದೆ" },
  days_to_return: { hi: "दिन में वापस आएँ", kn: "ದಿನಗಳಲ್ಲಿ ಮರಳಿ" },
  past_window: {
    hi: "सामान्य {n} दिन से ज़्यादा हो गया",
    kn: "ಸಾಮಾನ್ಯ {n} ದಿನಗಳನ್ನು ಮೀರಿದೆ",
  },
  days_left: {
    hi: "{n} दिन बाद हम चिंता करेंगे",
    kn: "{n} ದಿನಗಳ ನಂತರ ನಾವು ಗಮನ ಕೊಡುತ್ತೇವೆ",
  },
  see_doctor_about_this: {
    hi: "इसके बारे में डॉक्टर को दिखाएँ",
    kn: "ಇದರ ಬಗ್ಗೆ ವೈದ್ಯರನ್ನು ಭೇಟಿಯಾಗಿ",
  },

  // The Loop Detector's rungs, in the patient's words. The CODE (L2,
  // L2_TREATMENT_REFRACTORY) is never translated and never hidden - it is the
  // same string a clinician sees on the same case, and that is the point: one
  // ladder, one vocabulary, two readings.
  ladder_L0_OBSERVED: { hi: "देखा जा रहा है", kn: "ಗಮನಿಸಲಾಗುತ್ತಿದೆ" },
  ladder_L1_REPEAT_PRESENTATION: { hi: "बार-बार दिखाया", kn: "ಪದೇ ಪದೇ ಭೇಟಿ" },
  ladder_L2_TREATMENT_REFRACTORY: { hi: "इलाज काम नहीं कर रहा", kn: "ಚಿಕಿತ್ಸೆ ಫಲಿಸುತ್ತಿಲ್ಲ" },
  ladder_L3_ESCALATE_NOW: { hi: "अभी आगे बढ़ाएँ", kn: "ಈಗಲೇ ಮುಂದಕ್ಕೆ" },
  meaning_L0_OBSERVED: {
    hi: "दर्ज है और नजर रखी जा रही है। अभी कुछ अटका नहीं है।",
    kn: "ದಾಖಲಿಸಲಾಗಿದೆ ಮತ್ತು ಗಮನಿಸಲಾಗುತ್ತಿದೆ. ಇನ್ನೂ ಏನೂ ಸಿಲುಕಿಲ್ಲ.",
  },
  meaning_L1_REPEAT_PRESENTATION: {
    hi: "इसके लिए एक से ज़्यादा बार दिखाया, पर कोई जाँच नहीं हुई।",
    kn: "ಇದಕ್ಕಾಗಿ ಒಂದಕ್ಕಿಂತ ಹೆಚ್ಚು ಬಾರಿ ಭೇಟಿಯಾಗಿದೆ, ಆದರೆ ಯಾವುದೇ ಪರೀಕ್ಷೆ ಆಗಿಲ್ಲ.",
  },
  meaning_L2_TREATMENT_REFRACTORY: {
    hi: "कम से कम दो बार इलाज हुआ और फिर भी ठीक नहीं हुआ।",
    kn: "ಕನಿಷ್ಠ ಎರಡು ಬಾರಿ ಚಿಕಿತ್ಸೆ ಆಗಿದೆ, ಆದರೂ ಗುಣವಾಗಿಲ್ಲ.",
  },
  meaning_L3_ESCALATE_NOW: {
    hi: "इलाज काम नहीं कर रहा और हालत बिगड़ रही है या फैल रही है।",
    kn: "ಚಿಕಿತ್ಸೆ ಫಲಿಸುತ್ತಿಲ್ಲ ಮತ್ತು ಸ್ಥಿತಿ ಹದಗೆಡುತ್ತಿದೆ ಅಥವಾ ಹರಡುತ್ತಿದೆ.",
  },

  // tiers - the patient-facing wording only. The clinical labels are never
  // translated, because they are never shown to a patient.
  tier_HIGH: { hi: "अभी डॉक्टर को दिखाएँ", kn: "ಈಗ ವೈದ್ಯರನ್ನು ಭೇಟಿಯಾಗಿ" },
  tier_MODERATE: { hi: "जाँच कराना ठीक रहेगा", kn: "ಪರಿಶೀಲಿಸುವುದು ಒಳ್ಳೆಯದು" },
  tier_LOW: { hi: "नजर रखते रहें", kn: "ಗಮನಿಸುತ್ತಿರಿ" },

  // ask
  ask_placeholder: {
    hi: "अपनी भाषा में पूछें…",
    kn: "ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಕೇಳಿ…",
  },
  send: { hi: "भेजें", kn: "ಕಳುಹಿಸಿ" },

  // next action
  next_steps: { hi: "आगे के कदम", kn: "ಮುಂದಿನ ಹೆಜ್ಜೆಗಳು" },
  step_done: { hi: "हो गया", kn: "ಮುಗಿದಿದೆ" },
  step_doing: { hi: "चल रहा है", kn: "ನಡೆಯುತ್ತಿದೆ" },
  step_todo: { hi: "करना है", kn: "ಮಾಡಬೇಕು" },
  step_overdue: { hi: "समय निकल गया", kn: "ಸಮಯ ಮೀರಿದೆ" },
  step_auto: { hi: "यह अपने आप पूरा होगा", kn: "ಇದು ತಾನಾಗಿ ಪೂರ್ಣವಾಗುತ್ತದೆ" },
  due_on: { hi: "तारीख", kn: "ದಿನಾಂಕ" },
  of_done: { hi: "में से पूरे", kn: "ರಲ್ಲಿ ಮುಗಿದಿದೆ" },
  escalated_note: {
    hi: "आपने बताया कि आराम नहीं हुआ। हमने आपके डॉक्टर को इसकी सूचना दे दी है और यह पैटर्न रिकॉर्ड में जोड़ दिया है।",
    kn: "ಸಹಾಯವಾಗಿಲ್ಲ ಎಂದು ನೀವು ತಿಳಿಸಿದ್ದೀರಿ. ನಾವು ನಿಮ್ಮ ವೈದ್ಯರಿಗೆ ತಿಳಿಸಿದ್ದೇವೆ ಮತ್ತು ಈ ಮಾದರಿಯನ್ನು ದಾಖಲೆಗೆ ಸೇರಿಸಿದ್ದೇವೆ.",
  },
  feeling_q: { hi: "अब आप कैसा महसूस कर रहे हैं?", kn: "ಈಗ ನೀವು ಹೇಗಿದ್ದೀರಿ?" },
  feeling_better: { hi: "बेहतर", kn: "ಉತ್ತಮ" },
  feeling_same: { hi: "वैसा ही", kn: "ಹಾಗೇ" },
  feeling_worse: { hi: "और खराब", kn: "ಹೆಚ್ಚು ಕೆಟ್ಟದಾಗಿ" },
  helped_q: { hi: "क्या इलाज से फ़ायदा हुआ?", kn: "ಚಿಕಿತ್ಸೆ ಸಹಾಯ ಮಾಡಿತೇ?" },
  helped_yes: { hi: "हाँ", kn: "ಹೌದು" },
  helped_partially: { hi: "थोड़ा", kn: "ಸ್ವಲ್ಪ" },
  helped_no: { hi: "नहीं", kn: "ಇಲ್ಲ" },
  helped_not_started: { hi: "अभी शुरू नहीं किया", kn: "ಇನ್ನೂ ಶುರುಮಾಡಿಲ್ಲ" },
  response_thanks: {
    hi: "बताने के लिए धन्यवाद। यह आपके रिकॉर्ड में जुड़ गया है।",
    kn: "ತಿಳಿಸಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದ. ಇದು ನಿಮ್ಮ ದಾಖಲೆಗೆ ಸೇರಿದೆ.",
  },
  submit: { hi: "जमा करें", kn: "ಸಲ್ಲಿಸಿ" },
  ask_title: { hi: "AIRA से पूछें", kn: "AIRA ಯನ್ನು ಕೇಳಿ" },
  ask_subtitle: {
    hi: "यह सिर्फ़ प्रकाशित स्वास्थ्य दिशानिर्देशों और आपके अपने रिकॉर्ड से जवाब देता है।",
    kn: "ಇದು ಪ್ರಕಟಿತ ಆರೋಗ್ಯ ಮಾರ್ಗಸೂಚಿಗಳಿಂದ ಮತ್ತು ನಿಮ್ಮ ಸ್ವಂತ ದಾಖಲೆಯಿಂದ ಮಾತ್ರ ಉತ್ತರಿಸುತ್ತದೆ.",
  },
  ask_intro: {
    hi: "AIRA आपको यह नहीं बताएगा कि आपको कैंसर है या नहीं — यह सिर्फ़ जाँच से पता चलता है। यह बता सकता है कि कोई तकलीफ़ कितने दिन से है, आगे आम तौर पर क्या होता है, और क्या मुफ़्त है।",
    kn: "ನಿಮಗೆ ಕ್ಯಾನ್ಸರ್ ಇದೆಯೇ ಎಂದು AIRA ಹೇಳುವುದಿಲ್ಲ — ಅದನ್ನು ಪರೀಕ್ಷೆ ಮಾತ್ರ ಹೇಳಬಲ್ಲದು. ತೊಂದರೆ ಎಷ್ಟು ದಿನದಿಂದ ಇದೆ, ಮುಂದೆ ಸಾಮಾನ್ಯವಾಗಿ ಏನಾಗುತ್ತದೆ, ಮತ್ತು ಏನು ಉಚಿತ ಎಂಬುದನ್ನು ಅದು ಹೇಳಬಲ್ಲದು.",
  },
  suggest_wait: { hi: "क्या एक महीना और रुकना ठीक है?", kn: "ಇನ್ನೊಂದು ತಿಂಗಳು ಕಾಯುವುದು ಸರಿಯೇ?" },
  suggest_cost: { hi: "क्या स्वास्थ्य केंद्र पैसे लेगा?", kn: "ಆರೋಗ್ಯ ಕೇಂದ್ರ ಹಣ ಕೇಳುತ್ತದೆಯೇ?" },
  suggest_say: { hi: "डॉक्टर से क्या कहूँ?", kn: "ವೈದ್ಯರಿಗೆ ಏನು ಹೇಳಬೇಕು?" },
  suggest_breast: { hi: "स्तन जाँच में क्या होता है?", kn: "ಸ್ತನ ತಪಾಸಣೆಯಲ್ಲಿ ಏನಾಗುತ್ತದೆ?" },
  chat_footer: {
    hi: "{n} दिशानिर्देश अंश · जवाब दिखाने से पहले स्रोतों से मिलाए जाते हैं",
    kn: "{n} ಮಾರ್ಗಸೂಚಿ ಭಾಗಗಳು · ಉತ್ತರಗಳನ್ನು ತೋರಿಸುವ ಮೊದಲು ಮೂಲಗಳೊಂದಿಗೆ ಪರಿಶೀಲಿಸಲಾಗುತ್ತದೆ",
  },
  where_from: { hi: "यह कहाँ से आया", kn: "ಇದು ಎಲ್ಲಿಂದ ಬಂತು" },
  hide: { hi: "छिपाएँ", kn: "ಮರೆಮಾಡಿ" },
  checking: { hi: "दिशानिर्देश देख रहे हैं", kn: "ಮಾರ್ಗಸೂಚಿಗಳನ್ನು ನೋಡುತ್ತಿದ್ದೇವೆ" },
  straight_from_guideline: {
    hi: "सीधे दिशानिर्देश से लिखा गया। AI का जवाब हमारी जाँच में पास नहीं हुआ, इसलिए आप मूल स्रोत पढ़ रहे हैं।",
    kn: "ನೇರವಾಗಿ ಮಾರ್ಗಸೂಚಿಯಿಂದ ಬರೆಯಲಾಗಿದೆ. AI ಬರೆದದ್ದು ನಮ್ಮ ಪರಿಶೀಲನೆಯಲ್ಲಿ ಉತ್ತೀರ್ಣವಾಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ನೀವು ಮೂಲವನ್ನೇ ಓದುತ್ತಿದ್ದೀರಿ.",
  },
  chat_error: {
    hi: "AIRA तक पहुँचने में कुछ गड़बड़ हुई। आपके रिकॉर्ड पर कोई असर नहीं पड़ा।",
    kn: "AIRA ತಲುಪುವಲ್ಲಿ ಏನೋ ತೊಂದರೆಯಾಯಿತು. ನಿಮ್ಮ ದಾಖಲೆಗೆ ಯಾವ ಪರಿಣಾಮವೂ ಇಲ್ಲ.",
  },

  // ── Reports page ──────────────────────────────────────────────────────
  reports_title: { hi: "आपकी रिपोर्ट", kn: "ನಿಮ್ಮ ವರದಿಗಳು" },
  reports_sub: {
    hi: "जाँच का नतीजा जोड़ें और AIRA उस जाँच के बारे में पूछना बंद कर देगा जो हो चुकी है।",
    kn: "ಪರೀಕ್ಷಾ ಫಲಿತಾಂಶ ಸೇರಿಸಿ, ಆಗಿರುವ ಪರೀಕ್ಷೆಯ ಬಗ್ಗೆ AIRA ಕೇಳುವುದನ್ನು ನಿಲ್ಲಿಸುತ್ತದೆ.",
  },
  add_report: { hi: "एक रिपोर्ट जोड़ें", kn: "ವರದಿ ಸೇರಿಸಿ" },
  reading: { hi: "पढ़ रहे हैं…", kn: "ಓದುತ್ತಿದೆ…" },
  reads_label: { hi: "पढ़ता है", kn: "ಓದುತ್ತದೆ" },
  reads_body: {
    hi: "टेक्स्ट फ़ाइल या PDF में लिखे नंबर — ब्लड काउंट, ESR, बलग़म और एक्स-रे के नतीजे।",
    kn: "ಪಠ್ಯ ಫೈಲ್ ಅಥವಾ PDF ನಲ್ಲಿ ಬರೆದ ಸಂಖ್ಯೆಗಳು — ರಕ್ತದ ಎಣಿಕೆ, ESR, ಕಫ ಮತ್ತು ಎಕ್ಸ್-ರೇ ಫಲಿತಾಂಶ.",
  },
  wont_label: { hi: "नहीं करेगा", kn: "ಮಾಡುವುದಿಲ್ಲ" },
  wont_body: {
    hi: "फ़ोटो नहीं पढ़ेगा। रिपोर्ट की तस्वीर डॉक्टर के लिए रखी जाती है, पर AIRA उसमें क्या है यह अनुमान नहीं लगाता।",
    kn: "ಫೋಟೋ ಓದುವುದಿಲ್ಲ. ವರದಿಯ ಚಿತ್ರ ವೈದ್ಯರಿಗಾಗಿ ಇಡಲಾಗುತ್ತದೆ, ಆದರೆ ಅದರಲ್ಲಿ ಏನಿದೆ ಎಂದು AIRA ಊಹಿಸುವುದಿಲ್ಲ.",
  },
  never_label: { hi: "कभी नहीं", kn: "ಎಂದಿಗೂ" },
  never_body: {
    hi: "किसी नतीजे का मतलब नहीं बताएगा। यह सामान्य सीमा दिखाता है और मतलब डॉक्टर पर छोड़ देता है।",
    kn: "ಯಾವುದೇ ಫಲಿತಾಂಶದ ಅರ್ಥ ಹೇಳುವುದಿಲ್ಲ. ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿ ತೋರಿಸಿ, ಅರ್ಥವನ್ನು ವೈದ್ಯರಿಗೆ ಬಿಡುತ್ತದೆ.",
  },
  read_n_results: { hi: "{n} नतीजे पढ़े", kn: "{n} ಫಲಿತಾಂಶ ಓದಲಾಗಿದೆ" },
  recorded_as_test: {
    hi: "एक जाँच के रूप में दर्ज किया गया जो हो चुकी है",
    kn: "ಆಗಿರುವ ಪರೀಕ್ಷೆಯಾಗಿ ದಾಖಲಿಸಲಾಗಿದೆ",
  },
  no_reports_title: { hi: "अभी कोई रिपोर्ट नहीं", kn: "ಇನ್ನೂ ಯಾವ ವರದಿಯೂ ಇಲ್ಲ" },
  no_reports_body: {
    hi: "अगर आपके पास ब्लड टेस्ट या एक्स-रे रिपोर्ट है, तो उसे यहाँ जोड़ें ताकि डॉक्टर उसे आपकी बाकी कहानी के साथ देखे।",
    kn: "ನಿಮ್ಮ ಬಳಿ ರಕ್ತ ಪರೀಕ್ಷೆ ಅಥವಾ ಎಕ್ಸ್-ರೇ ವರದಿ ಇದ್ದರೆ, ವೈದ್ಯರು ಅದನ್ನು ನಿಮ್ಮ ಕಥೆಯೊಂದಿಗೆ ನೋಡುವಂತೆ ಇಲ್ಲಿ ಸೇರಿಸಿ.",
  },
  values_read: { hi: "मान पढ़े गए", kn: "ಮೌಲ್ಯಗಳು ಓದಲಾಗಿದೆ" },
  photo_not_read: { hi: "फ़ोटो, पढ़ी नहीं गई", kn: "ಫೋಟೋ, ಓದಿಲ್ಲ" },
  outside_range: { hi: "सीमा से बाहर", kn: "ವ್ಯಾಪ್ತಿ ಮೀರಿ" },
  usual_range: { hi: "सामान्य", kn: "ಸಾಮಾನ್ಯ" },
  status_low: { hi: "सामान्य सीमा से नीचे", kn: "ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಗಿಂತ ಕಡಿಮೆ" },
  status_high: { hi: "सामान्य सीमा से ऊपर", kn: "ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಗಿಂತ ಹೆಚ್ಚು" },
  status_normal: { hi: "सामान्य सीमा में", kn: "ಸಾಮಾನ್ಯ ವ್ಯಾಪ್ತಿಯಲ್ಲಿ" },
  status_reported: { hi: "दर्ज किया गया", kn: "ದಾಖಲಿಸಲಾಗಿದೆ" },

  // ── Notes (from your doctor) ──────────────────────────────────────────
  notes_title: { hi: "आपके डॉक्टर से", kn: "ನಿಮ್ಮ ವೈದ್ಯರಿಂದ" },
  notes_sub: {
    hi: "जिस डॉक्टर ने आपको देखा, उन्हीं के शब्दों में, आपकी भाषा में।",
    kn: "ನಿಮ್ಮನ್ನು ನೋಡಿದ ವೈದ್ಯರ ಸ್ವಂತ ಮಾತುಗಳಲ್ಲಿ, ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ.",
  },
  notes_empty_title: { hi: "अभी कुछ नहीं", kn: "ಇನ್ನೂ ಏನೂ ಇಲ್ಲ" },
  notes_empty_body: {
    hi: "किसी जाँच के बाद आपका डॉक्टर आगे क्या होगा उसके बारे में एक छोटा नोट भेज सकता है। वह यहाँ दिखेगा।",
    kn: "ಭೇಟಿಯ ನಂತರ ನಿಮ್ಮ ವೈದ್ಯರು ಮುಂದೇನಾಗುತ್ತದೆ ಎಂಬ ಒಂದು ಸಣ್ಣ ಟಿಪ್ಪಣಿ ಕಳುಹಿಸಬಹುದು. ಅದು ಇಲ್ಲಿ ಕಾಣಿಸುತ್ತದೆ.",
  },
  tests_to_have: { hi: "जो जाँच करानी है", kn: "ಮಾಡಿಸಬೇಕಾದ ಪರೀಕ್ಷೆಗಳು" },
  come_back_in: { hi: "वापस आएँ", kn: "ಮರಳಿ ಬನ್ನಿ" },

  // ── Timeline (your story) ─────────────────────────────────────────────
  timeline_title: { hi: "अब तक आपकी कहानी", kn: "ಇಲ್ಲಿಯವರೆಗಿನ ನಿಮ್ಮ ಕಥೆ" },
  timeline_sub: {
    hi: "हर डॉक्टर ने इसकी एक लाइन देखी। AIRA अकेला है जो पूरा पन्ना पकड़े हुए है।",
    kn: "ಪ್ರತಿ ವೈದ್ಯರೂ ಇದರ ಒಂದು ಸಾಲನ್ನು ನೋಡಿದರು. ಇಡೀ ಪುಟವನ್ನು ಹಿಡಿದಿರುವುದು AIRA ಒಂದೇ.",
  },
  timeline_empty_title: { hi: "अभी कुछ दर्ज नहीं", kn: "ಇನ್ನೂ ಏನೂ ದಾಖಲಾಗಿಲ್ಲ" },
  timeline_empty_body: {
    hi: "एक लक्षण जोड़ें और आपकी कहानी यहाँ से शुरू होती है।",
    kn: "ಒಂದು ಲಕ್ಷಣ ಸೇರಿಸಿ, ನಿಮ್ಮ ಕಥೆ ಇಲ್ಲಿಂದ ಶುರುವಾಗುತ್ತದೆ.",
  },
  gap_visits: {
    hi: "{n} बार गए जब कोई जाँच नहीं कराई गई",
    kn: "{n} ಬಾರಿ ಭೇಟಿ, ಯಾವ ಪರೀಕ್ಷೆಯೂ ಆಗಲಿಲ್ಲ",
  },
  gap_note: {
    hi: "यह किसी एक डॉक्टर की गलती नहीं है। हर कोई उस दिन ठीक फ़ैसला ले रहा था। यह सिर्फ़ तब दिखता है जब आप सबको एक साथ रखते हैं।",
    kn: "ಇದು ಯಾವುದೇ ಒಬ್ಬ ವೈದ್ಯರ ತಪ್ಪಲ್ಲ. ಪ್ರತಿಯೊಬ್ಬರೂ ಆ ದಿನ ಸರಿಯಾದ ನಿರ್ಧಾರ ತೆಗೆದುಕೊಳ್ಳುತ್ತಿದ್ದರು. ಎಲ್ಲವನ್ನೂ ಒಟ್ಟಿಗೆ ಇಟ್ಟಾಗ ಮಾತ್ರ ಇದು ಕಾಣಿಸುತ್ತದೆ.",
  },
  no_test_ordered: { hi: "कोई जाँच नहीं करवाई गई", kn: "ಯಾವ ಪರೀಕ್ಷೆಯೂ ಆಗಲಿಲ್ಲ" },
  tl_symptom_started: { hi: "लक्षण शुरू हुआ", kn: "ಲಕ್ಷಣ ಶುರುವಾಯಿತು" },
  tl_visit: { hi: "डॉक्टर के पास गए", kn: "ವೈದ್ಯರ ಭೇಟಿ" },
  tl_checkin: { hi: "फ़ॉलो-अप का जवाब दिया", kn: "ಫಾಲೋ-ಅಪ್ ಉತ್ತರಿಸಿದೆ" },
  tl_safe_window: { hi: "सामान्य समय {n} दिन", kn: "ಸಾಮಾನ್ಯ ಅವಧಿ {n} ದಿನ" },
  tl_given: { hi: "दिया गया", kn: "ನೀಡಲಾಗಿದೆ" },
  tl_tested: { hi: "जाँच", kn: "ಪರೀಕ್ಷೆ" },
  tl_result: { hi: "नतीजा", kn: "ಫಲಿತಾಂಶ" },

  // ── Screening (free checks) ──────────────────────────────────────────
  screening_title: { hi: "मुफ़्त जाँच जो आप करा सकते हैं", kn: "ನೀವು ಪಡೆಯಬಹುದಾದ ಉಚಿತ ತಪಾಸಣೆ" },
  screening_sub: {
    hi: "गैर-संचारी रोगों के राष्ट्रीय कार्यक्रम के तहत सरकार चलाती है। यहाँ किसी चीज़ का पैसा नहीं लगता, और इसका मतलब यह नहीं कि कुछ गड़बड़ है।",
    kn: "ಸಾಂಕ್ರಾಮಿಕವಲ್ಲದ ರೋಗಗಳ ರಾಷ್ಟ್ರೀಯ ಕಾರ್ಯಕ್ರಮದಡಿ ಸರ್ಕಾರ ನಡೆಸುತ್ತದೆ. ಇಲ್ಲಿ ಏನಕ್ಕೂ ಹಣ ಇಲ್ಲ, ಮತ್ತು ಏನೋ ತಪ್ಪಾಗಿದೆ ಎಂದಲ್ಲ.",
  },
  screening_empty_title: { hi: "अभी कुछ बाकी नहीं", kn: "ಈಗ ಏನೂ ಬಾಕಿ ಇಲ್ಲ" },
  screening_empty_body: {
    hi: "जब कुछ करवाना होगा तो हम आपको बताएँगे।",
    kn: "ಏನಾದರೂ ಮಾಡಬೇಕಾದಾಗ ನಾವು ನಿಮಗೆ ತಿಳಿಸುತ್ತೇವೆ.",
  },
  scr_test: { hi: "जाँच", kn: "ಪರೀಕ್ಷೆ" },
  scr_where: { hi: "कहाँ", kn: "ಎಲ್ಲಿ" },
  scr_who: { hi: "कौन करता है", kn: "ಯಾರು ಮಾಡುತ್ತಾರೆ" },
  scr_how_often: { hi: "कितनी बार", kn: "ಎಷ್ಟು ಬಾರಿ" },
  scr_every_years: { hi: "हर {n} साल", kn: "ಪ್ರತಿ {n} ವರ್ಷಕ್ಕೊಮ್ಮೆ" },
  scr_every_months: { hi: "हर {n} महीने", kn: "ಪ್ರತಿ {n} ತಿಂಗಳಿಗೊಮ್ಮೆ" },
  scr_more_often: {
    hi: "आपके लिए ज़्यादा बार, तंबाकू के इस्तेमाल की वजह से।",
    kn: "ತಂಬಾಕು ಬಳಕೆಯ ಕಾರಣ ನಿಮಗೆ ಹೆಚ್ಚು ಬಾರಿ.",
  },

  // ── Access (who can see your record) ─────────────────────────────────
  access_title: { hi: "आपका रिकॉर्ड कौन देख सकता है", kn: "ನಿಮ್ಮ ದಾಖಲೆ ಯಾರು ನೋಡಬಹುದು" },
  access_sub: {
    hi: "कोई नहीं, जब तक आप न कहें। आप इसे कभी भी वापस ले सकते हैं और यह तुरंत काम करना बंद कर देता है।",
    kn: "ನೀವು ಹೇಳುವವರೆಗೆ ಯಾರೂ ಇಲ್ಲ. ನೀವು ಯಾವಾಗ ಬೇಕಾದರೂ ಇದನ್ನು ಹಿಂಪಡೆಯಬಹುದು ಮತ್ತು ಅದು ತಕ್ಷಣ ಕೆಲಸ ನಿಲ್ಲಿಸುತ್ತದೆ.",
  },
  your_aira_code: { hi: "आपका AIRA कोड", kn: "ನಿಮ್ಮ AIRA ಕೋಡ್" },
  code_hint: {
    hi: "यह कोड और एक बार का PIN डॉक्टर को दें। अकेला कोड कुछ नहीं करता।",
    kn: "ಈ ಕೋಡ್ ಮತ್ತು ಒಂದು ಬಾರಿಯ PIN ಅನ್ನು ವೈದ್ಯರಿಗೆ ಕೊಡಿ. ಕೋಡ್ ಒಂದೇ ಏನೂ ಮಾಡುವುದಿಲ್ಲ.",
  },
  generate_pin: { hi: "एक PIN बनाएँ", kn: "ಒಂದು PIN ರಚಿಸಿ" },
  pin_valid_for: {
    hi: "{n} मिनट के लिए वैध। इसे बोलकर बताएँ; मैसेज में न भेजें।",
    kn: "{n} ನಿಮಿಷಗಳವರೆಗೆ ಮಾನ್ಯ. ಇದನ್ನು ಹೇಳಿ; ಸಂದೇಶದಲ್ಲಿ ಕಳುಹಿಸಬೇಡಿ.",
  },
  waiting_your_answer: { hi: "आपके जवाब का इंतज़ार", kn: "ನಿಮ್ಮ ಉತ್ತರಕ್ಕಾಗಿ ಕಾಯುತ್ತಿದೆ" },
  asked_at: { hi: "पूछा गया", kn: "ಕೇಳಲಾಗಿದೆ" },
  read_what_they_see: { hi: "वे क्या देखेंगे यह पढ़ें", kn: "ಅವರು ಏನು ನೋಡುತ್ತಾರೆ ಎಂದು ಓದಿ" },
  no_btn: { hi: "नहीं", kn: "ಇಲ್ಲ" },
  yes_let_them: { hi: "हाँ, उन्हें देखने दें", kn: "ಹೌದು, ಅವರಿಗೆ ತೋರಿಸಿ" },
  doctors_with_access: { hi: "जिनके पास पहुँच है", kn: "ಪ್ರವೇಶ ಇರುವ ವೈದ್ಯರು" },
  nobody_can_see: {
    hi: "अभी कोई आपका रिकॉर्ड नहीं देख सकता।",
    kn: "ಈಗ ಯಾರೂ ನಿಮ್ಮ ದಾಖಲೆ ನೋಡಲಾಗುವುದಿಲ್ಲ.",
  },
  take_it_back: { hi: "वापस लें", kn: "ಹಿಂಪಡೆಯಿರಿ" },
  given_on: { hi: "दिया गया", kn: "ನೀಡಲಾಗಿದೆ" },
  expires_on: { hi: "ख़त्म होगा", kn: "ಕೊನೆಗೊಳ್ಳುತ್ತದೆ" },
  read_aloud_at: { hi: "· सूचना पढ़कर सुनाई गई", kn: "· ಸೂಚನೆಯನ್ನು ಓದಿ ಕೇಳಿಸಲಾಗಿದೆ" },
  scope_symptoms: { hi: "लक्षण", kn: "ಲಕ್ಷಣಗಳು" },
  scope_episodes: { hi: "डॉक्टर विज़िट", kn: "ವೈದ್ಯರ ಭೇಟಿಗಳು" },
  scope_assessments: { hi: "आकलन", kn: "ಮೌಲ್ಯಮಾಪನಗಳು" },
  scope_documents: { hi: "रिपोर्ट", kn: "ವರದಿಗಳು" },
  scope_screening: { hi: "जाँच की स्थिति", kn: "ತಪಾಸಣೆ ಸ್ಥಿತಿ" },
  past_label: { hi: "पहले", kn: "ಹಿಂದೆ" },
  before_you_decide: { hi: "फ़ैसला करने से पहले", kn: "ನಿರ್ಧರಿಸುವ ಮೊದಲು" },
  read_this_to_me: { hi: "यह मुझे पढ़कर सुनाएँ", kn: "ಇದನ್ನು ನನಗೆ ಓದಿ ಕೇಳಿಸಿ" },
  reading_it_out: { hi: "पढ़कर सुना रहे हैं…", kn: "ಓದಿ ಕೇಳಿಸುತ್ತಿದೆ…" },
  access_ends_after: {
    hi: "पहुँच {n} दिन बाद अपने आप ख़त्म हो जाती है, और आप इसे इस स्क्रीन से पहले भी बंद कर सकते हैं।",
    kn: "ಪ್ರವೇಶ {n} ದಿನಗಳ ನಂತರ ತಾನಾಗಿ ಕೊನೆಗೊಳ್ಳುತ್ತದೆ, ಮತ್ತು ನೀವು ಇದನ್ನು ಈ ಪರದೆಯಿಂದ ಮೊದಲೇ ನಿಲ್ಲಿಸಬಹುದು.",
  },
  consent_abdm_note: {
    hi: "यह ABDM सहमति मॉडल जैसा है: एक सीमित, उद्देश्य-बद्ध, समय-बद्ध, वापस लिया जा सकने वाला दस्तावेज़, जिसकी हर बार पढ़ने की एंट्री एक स्थायी ऑडिट लॉग में दर्ज होती है।",
    kn: "ಇದು ABDM ಸಮ್ಮತಿ ಮಾದರಿಯಂತಿದೆ: ಒಂದು ಸೀಮಿತ, ಉದ್ದೇಶ-ಬದ್ಧ, ಸಮಯ-ಬದ್ಧ, ಹಿಂಪಡೆಯಬಹುದಾದ ದಾಖಲೆ, ಪ್ರತಿ ಓದುವಿಕೆಯೂ ಶಾಶ್ವತ ಆಡಿಟ್ ಲಾಗ್‌ನಲ್ಲಿ ದಾಖಲಾಗುತ್ತದೆ.",
  },
  cstatus_REVOKED: { en: "Revoked", hi: "वापस लिया", kn: "ಹಿಂಪಡೆಯಲಾಗಿದೆ" },
  cstatus_DENIED: { en: "Declined", hi: "मना किया", kn: "ನಿರಾಕರಿಸಲಾಗಿದೆ" },
  cstatus_EXPIRED: { en: "Expired", hi: "समय ख़त्म", kn: "ಅವಧಿ ಮುಗಿದಿದೆ" },

  // ── Handoff card ─────────────────────────────────────────────────────
  card_title: { hi: "आपके डॉक्टर के लिए कार्ड", kn: "ನಿಮ್ಮ ವೈದ್ಯರಿಗಾಗಿ ಕಾರ್ಡ್" },
  card_sub: {
    hi: "यह दिखाएँ, या प्रिंट करें। यह एक पन्ना है और इसमें सब तथ्य हैं।",
    kn: "ಇದನ್ನು ತೋರಿಸಿ, ಅಥವಾ ಮುದ್ರಿಸಿ. ಇದು ಒಂದು ಪುಟ ಮತ್ತು ಇದರಲ್ಲಿ ಎಲ್ಲಾ ಸತ್ಯಗಳಿವೆ.",
  },
  print: { hi: "प्रिंट", kn: "ಮುದ್ರಿಸಿ" },
  card_no_card_title: { hi: "अभी कोई कार्ड नहीं", kn: "ಇನ್ನೂ ಕಾರ್ಡ್ ಇಲ್ಲ" },
  card_no_card_body: {
    hi: "पहले एक लक्षण ट्रैक करें, फिर आपके लिए एक कार्ड बनता है।",
    kn: "ಮೊದಲು ಒಂದು ಲಕ್ಷಣ ಗಮನಿಸಿ, ನಂತರ ನಿಮಗಾಗಿ ಕಾರ್ಡ್ ರಚನೆಯಾಗುತ್ತದೆ.",
  },
  card_anchor: { hi: "मुख्य लक्षण", kn: "ಮುಖ್ಯ ಲಕ್ಷಣ" },
  card_days: { hi: "दिन", kn: "ದಿನ" },
  card_window: { hi: "सामान्य {n} दिन", kn: "ಸಾಮಾನ್ಯ {n} ದಿನ" },
  card_overdue_by: { hi: "इतना ज़्यादा हो गया", kn: "ಇಷ್ಟು ಮೀರಿದೆ" },
  card_doctors_seen: { hi: "देखे गए डॉक्टर", kn: "ಭೇಟಿಯಾದ ವೈದ್ಯರು" },
  card_places: { hi: "{n} जगह", kn: "{n} ಸ್ಥಳ" },
  card_tests_ordered: { hi: "करवाई गई जाँच", kn: "ಮಾಡಿಸಿದ ಪರೀಕ್ಷೆಗಳು" },
  card_tx_failed: { hi: "{n} इलाज असफल", kn: "{n} ಚಿಕಿತ್ಸೆ ವಿಫಲ" },
  card_already_tried: { hi: "अब तक क्या आज़माया गया है", kn: "ಇಲ್ಲಿಯವರೆಗೆ ಏನು ಪ್ರಯತ್ನಿಸಲಾಗಿದೆ" },
  col_date: { hi: "तारीख", kn: "ದಿನಾಂಕ" },
  col_where: { hi: "कहाँ", kn: "ಎಲ್ಲಿ" },
  col_given: { hi: "दिया गया", kn: "ನೀಡಲಾಗಿದೆ" },
  col_tested: { hi: "जाँच", kn: "ಪರೀಕ್ಷೆ" },
  col_result: { hi: "नतीजा", kn: "ಫಲಿತಾಂಶ" },
  col_none: { hi: "कोई नहीं", kn: "ಯಾವುದೂ ಇಲ್ಲ" },
  card_why: { hi: "AIRA ने इसे क्यों चिह्नित किया", kn: "AIRA ಇದನ್ನು ಏಕೆ ಗುರುತಿಸಿತು" },
  card_guidelines_point: { hi: "दिशानिर्देश किस ओर इशारा करते हैं", kn: "ಮಾರ್ಗಸೂಚಿಗಳು ಯಾವ ಕಡೆ ಸೂಚಿಸುತ್ತವೆ" },
  card_guidelines_note: {
    hi: "प्रकाशित रेफ़रल मानदंडों से सुझाव। फ़ैसला डॉक्टर का है, और AIRA यह दर्ज करता है।",
    kn: "ಪ್ರಕಟಿತ ಶಿಫಾರಸು ಮಾನದಂಡಗಳಿಂದ ಸಲಹೆಗಳು. ನಿರ್ಧಾರ ವೈದ್ಯರದ್ದು, ಮತ್ತು AIRA ಅದನ್ನು ದಾಖಲಿಸುತ್ತದೆ.",
  },
  generated: { hi: "बनाया गया", kn: "ರಚಿಸಲಾಗಿದೆ" },

  // ── Check-in modal ───────────────────────────────────────────────────
  checkin_title: { hi: "हाल पूछ रहे हैं", kn: "ಕುಶಲ ವಿಚಾರಿಸುತ್ತಿದ್ದೇವೆ" },
  how_bad_now: { hi: "अब कितनी तकलीफ़ है? ({n}/10)", kn: "ಈಗ ಎಷ್ಟು ತೊಂದರೆ ಇದೆ? ({n}/10)" },
  saving: { hi: "सहेज रहे हैं…", kn: "ಉಳಿಸುತ್ತಿದೆ…" },

  // ── Add a symptom modal ──────────────────────────────────────────────
  as_title: { hi: "एक लक्षण जोड़ें", kn: "ಒಂದು ಲಕ್ಷಣ ಸೇರಿಸಿ" },
  as_tab_tick: { hi: "सूची में से चुनें", kn: "ಪಟ್ಟಿಯಿಂದ ಆರಿಸಿ" },
  as_tab_voice: { hi: "बोलकर या लिखकर बताएँ", kn: "ಮಾತನಾಡಿ ಅಥವಾ ಬರೆಯಿರಿ" },
  as_loading: { hi: "लक्षण लोड हो रहे हैं", kn: "ಲಕ್ಷಣಗಳು ಲೋಡ್ ಆಗುತ್ತಿವೆ" },
  as_search: { hi: "खोजें — जैसे 'खाँसी' या 'गाँठ'", kn: "ಹುಡುಕಿ — ಉದಾ. 'ಕೆಮ್ಮು' ಅಥವಾ 'ಗಂಟು'" },
  as_no_match: {
    hi: "\"{q}\" से कुछ नहीं मिला। दूसरा टैब आज़माएँ और अपने शब्दों में बताएँ।",
    kn: "\"{q}\" ಗೆ ಏನೂ ಹೊಂದಿಕೆಯಾಗಲಿಲ್ಲ. ಬೇರೆ ಟ್ಯಾಬ್ ಪ್ರಯತ್ನಿಸಿ, ನಿಮ್ಮ ಮಾತಿನಲ್ಲಿ ಹೇಳಿ.",
  },
  as_speak_or_type: { hi: "बोलें या लिखें", kn: "ಮಾತನಾಡಿ ಅಥವಾ ಬರೆಯಿರಿ" },
  as_textarea: {
    hi: "अपने शब्दों में बताएँ — “तीन हफ़्ते से खाँसी है और वजन घट रहा है”",
    kn: "ನಿಮ್ಮ ಮಾತಿನಲ್ಲಿ ಹೇಳಿ — “ಮೂರು ವಾರಗಳಿಂದ ಕೆಮ್ಮು ಇದೆ ಮತ್ತು ತೂಕ ಇಳಿಯುತ್ತಿದೆ”",
  },
  as_listening: { hi: "सुन रहे हैं… रोकने के लिए टैप करें", kn: "ಕೇಳುತ್ತಿದೆ… ನಿಲ್ಲಿಸಲು ಟ್ಯಾಪ್ ಮಾಡಿ" },
  as_speak_instead: { hi: "बोलकर बताएँ", kn: "ಮಾತನಾಡಿ ಹೇಳಿ" },
  as_recording: { hi: "रिकॉर्ड हो रहा है… रोकने के लिए टैप करें", kn: "ರೆಕಾರ್ಡ್ ಆಗುತ್ತಿದೆ… ನಿಲ್ಲಿಸಲು ಟ್ಯಾಪ್ ಮಾಡಿ" },
  as_record_in: { hi: "हिन्दी में रिकॉर्ड करें", kn: "ಕನ್ನಡದಲ್ಲಿ ರೆಕಾರ್ಡ್ ಮಾಡಿ" },
  as_what_did_i_say: { hi: "मैंने क्या कहा?", kn: "ನಾನು ಏನು ಹೇಳಿದೆ?" },
  as_voice_mock: {
    hi: "स्पीच-टू-टेक्स्ट अभी मॉक मोड में है। अपनी भाषा में लिखने से काम चलता है — AIRA को हर लक्षण के हिंदी और कन्नड़ शब्द पहले से पता हैं।",
    kn: "ಸ್ಪೀಚ್-ಟು-ಟೆಕ್ಸ್ಟ್ ಈಗ ಮಾಕ್ ಮೋಡ್‌ನಲ್ಲಿದೆ. ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಬರೆಯುವುದು ಕೆಲಸ ಮಾಡುತ್ತದೆ — ಪ್ರತಿ ಲಕ್ಷಣದ ಹಿಂದಿ ಮತ್ತು ಕನ್ನಡ ಪದಗಳು AIRA ಗೆ ಈಗಾಗಲೇ ತಿಳಿದಿವೆ.",
  },
  as_no_speech: {
    hi: "स्पीच सेवा से कुछ नहीं आया। इसके बजाय लिखें, या सूची का इस्तेमाल करें।",
    kn: "ಸ್ಪೀಚ್ ಸೇವೆಯಿಂದ ಏನೂ ಬರಲಿಲ್ಲ. ಬದಲಿಗೆ ಬರೆಯಿರಿ, ಅಥವಾ ಪಟ್ಟಿ ಬಳಸಿ.",
  },
  as_no_mic: {
    hi: "इस डिवाइस ने माइक इस्तेमाल नहीं करने दिया।",
    kn: "ಈ ಸಾಧನ ಮೈಕ್ ಬಳಸಲು ಬಿಡಲಿಲ್ಲ.",
  },
  as_no_candidates: {
    hi: "हम इसे किसी ट्रैक की जाने वाली चीज़ से नहीं मिला पाए। सूची आज़माएँ।",
    kn: "ಇದನ್ನು ನಾವು ಗಮನಿಸುವ ಯಾವುದಕ್ಕೂ ಹೊಂದಿಸಲಾಗಲಿಲ್ಲ. ಪಟ್ಟಿ ಪ್ರಯತ್ನಿಸಿ.",
  },
  as_is_this: { hi: "क्या आपका यही मतलब था?", kn: "ನೀವು ಹೇಳಿದ್ದು ಇದೇನಾ?" },
  as_matched_on: { hi: "मिलान", kn: "ಹೊಂದಿಕೆ" },
  as_also_heard: {
    hi: "हमने <b>{n} दिन</b> भी सुना। आप इसे आगे बदल सकते हैं।",
    kn: "ನಾವು <b>{n} ದಿನ</b> ಎಂದೂ ಕೇಳಿದೆವು. ಇದನ್ನು ನೀವು ಮುಂದೆ ಬದಲಾಯಿಸಬಹುದು.",
  },
  as_choose_else: { hi: "← कुछ और चुनें", kn: "← ಬೇರೆ ಆರಿಸಿ" },
  as_how_long: { hi: "यह कितने समय से हो रहा है?", kn: "ಇದು ಎಷ್ಟು ಕಾಲದಿಂದ ಆಗುತ್ತಿದೆ?" },
  as_days: { hi: "{n} दिन", kn: "{n} ದಿನ" },
  as_months: { hi: "{n} महीने", kn: "{n} ತಿಂಗಳು" },
  as_date_note: {
    hi: "तारीख बाकी सब चीज़ों से ज़्यादा मायने रखती है। AIRA का हर नियम इसी दिन से शुरू हुई एक घड़ी है।",
    kn: "ದಿನಾಂಕ ಉಳಿದೆಲ್ಲಕ್ಕಿಂತ ಹೆಚ್ಚು ಮುಖ್ಯ. AIRA ದ ಪ್ರತಿ ನಿಯಮವೂ ಈ ದಿನದಿಂದ ಶುರುವಾದ ಒಂದು ಗಡಿಯಾರ.",
  },
  as_how_bad: { hi: "अभी कितनी तकलीफ़ है? ({n}/10)", kn: "ಈಗ ಎಷ್ಟು ತೊಂದರೆ ಇದೆ? ({n}/10)" },
  as_barely: { hi: "बहुत हल्की", kn: "ಬಹಳ ಸ್ವಲ್ಪ" },
  as_worst: { hi: "जितनी बुरी हो सकती है", kn: "ಅತ್ಯಂತ ಕೆಟ್ಟದಾಗಿ" },
  as_start_tracking: { hi: "इसे ट्रैक करना शुरू करें", kn: "ಇದನ್ನು ಗಮನಿಸಲು ಶುರುಮಾಡಿ" },

  // ── Record a visit modal ─────────────────────────────────────────────
  rv_title: { hi: "डॉक्टर की एक विज़िट दर्ज करें", kn: "ವೈದ್ಯರ ಒಂದು ಭೇಟಿ ದಾಖಲಿಸಿ" },
  rv_when: { hi: "आप कब गए?", kn: "ನೀವು ಯಾವಾಗ ಹೋದಿರಿ?" },
  rv_about: { hi: "किस बारे में था?", kn: "ಯಾವುದರ ಬಗ್ಗೆ ಆಗಿತ್ತು?" },
  rv_where: { hi: "आप कहाँ गए?", kn: "ನೀವು ಎಲ್ಲಿ ಹೋದಿರಿ?" },
  rv_given: { hi: "आपको क्या दिया गया?", kn: "ನಿಮಗೆ ಏನು ನೀಡಲಾಯಿತು?" },
  rv_tested_q: {
    hi: "क्या किसी ने सैंपल भेजा, स्कैन किया, या एक्स-रे लिया?",
    kn: "ಯಾರಾದರೂ ಮಾದರಿ ಕಳುಹಿಸಿದರೇ, ಸ್ಕ್ಯಾನ್ ಮಾಡಿದರೇ, ಅಥವಾ ಎಕ್ಸ್-ರೇ ತೆಗೆದರೇ?",
  },
  rv_no_just_med: { hi: "नहीं, सिर्फ़ दवा", kn: "ಇಲ್ಲ, ಕೇವಲ ಔಷಧಿ" },
  rv_yes_test: { hi: "हाँ, एक जाँच हुई", kn: "ಹೌದು, ಒಂದು ಪರೀಕ್ಷೆ ಆಯಿತು" },
  rv_which_test: {
    hi: "कौन सी जाँच, अगर याद हो (जैसे चेस्ट एक्स-रे)",
    kn: "ಯಾವ ಪರೀಕ್ಷೆ, ನೆನಪಿದ್ದರೆ (ಉದಾ. ಎದೆ ಎಕ್ಸ್-ರೇ)",
  },
  rv_test_note: {
    hi: "जो जाँच सच में हुई है वह AIRA का पूछना बंद कर देती है। यही बात है — यह विज़िट नहीं गिन रहा, यह अनुत्तरित सवाल गिन रहा है।",
    kn: "ನಿಜವಾಗಿ ಆದ ಪರೀಕ್ಷೆ AIRA ಕೇಳುವುದನ್ನು ನಿಲ್ಲಿಸುತ್ತದೆ. ಅದೇ ವಿಷಯ — ಇದು ಭೇಟಿಗಳನ್ನು ಎಣಿಸುತ್ತಿಲ್ಲ, ಉತ್ತರವಿಲ್ಲದ ಪ್ರಶ್ನೆಗಳನ್ನು ಎಣಿಸುತ್ತಿದೆ.",
  },
  rv_did_help: { hi: "क्या इससे फ़ायदा हुआ?", kn: "ಇದರಿಂದ ಸಹಾಯವಾಯಿತೇ?" },
  rv_save: { hi: "यह विज़िट सहेजें", kn: "ಈ ಭೇಟಿ ಉಳಿಸಿ" },

  // ── Vocab: providers ────────────────────────────────────────────────
  prov_phc: { en: "Primary health centre", hi: "प्राथमिक स्वास्थ्य केंद्र", kn: "ಪ್ರಾಥಮಿಕ ಆರೋಗ್ಯ ಕೇಂದ್ರ" },
  prov_chc: { en: "Community health centre", hi: "सामुदायिक स्वास्थ्य केंद्र", kn: "ಸಮುದಾಯ ಆರೋಗ್ಯ ಕೇಂದ್ರ" },
  prov_private_clinic: { en: "Private clinic", hi: "प्राइवेट क्लिनिक", kn: "ಖಾಸಗಿ ಚಿಕಿತ್ಸಾಲಯ" },
  prov_chemist: { en: "Chemist / pharmacy", hi: "मेडिकल स्टोर", kn: "ಔಷಧ ಅಂಗಡಿ" },
  prov_district_hospital: { en: "District hospital", hi: "ज़िला अस्पताल", kn: "ಜಿಲ್ಲಾ ಆಸ್ಪತ್ರೆ" },
  prov_ayush: { en: "AYUSH practitioner", hi: "आयुष चिकित्सक", kn: "ಆಯುಷ್ ವೈದ್ಯರು" },
  prov_unknown: { en: "Not recorded", hi: "दर्ज नहीं", kn: "ದಾಖಲಾಗಿಲ್ಲ" },

  // ── Vocab: interventions ────────────────────────────────────────────
  int_none: { en: "No treatment given", hi: "कोई इलाज नहीं दिया", kn: "ಚಿಕಿತ್ಸೆ ನೀಡಿಲ್ಲ" },
  int_antacid: { en: "Antacid", hi: "एंटासिड", kn: "ಆ್ಯಂಟಾಸಿಡ್" },
  int_antibiotic: { en: "Antibiotic", hi: "एंटीबायोटिक", kn: "ಆ್ಯಂಟಿಬಯಾಟಿಕ್" },
  int_att: { en: "Anti-TB treatment", hi: "टीबी की दवा", kn: "ಟಿಬಿ ಔಷಧ" },
  int_painkiller: { en: "Painkiller", hi: "दर्द की दवा", kn: "ನೋವಿನ ಔಷಧ" },
  int_vitamin: { en: "Vitamins / tonic", hi: "विटामिन / टॉनिक", kn: "ವಿಟಮಿನ್ / ಟಾನಿಕ್" },
  int_other: { en: "Other", hi: "अन्य", kn: "ಇತರೆ" },

  // ── Vocab: outcomes ─────────────────────────────────────────────────
  out_unchanged: { en: "No better", hi: "कोई फ़र्क नहीं", kn: "ಸುಧಾರಿಸಿಲ್ಲ" },
  out_worse: { en: "Worse", hi: "और खराब", kn: "ಹೆಚ್ಚು ಕೆಟ್ಟದಾಗಿ" },
  out_resolved: { en: "It went away", hi: "ठीक हो गया", kn: "ಗುಣವಾಯಿತು" },
  out_partial: { en: "A little better", hi: "थोड़ा बेहतर", kn: "ಸ್ವಲ್ಪ ಉತ್ತಮ" },
  out_unknown: { en: "Not recorded", hi: "दर्ज नहीं", kn: "ದಾಖಲಾಗಿಲ್ಲ" },
  out_same: { en: "Still the same", hi: "वैसा ही है", kn: "ಹಾಗೇ ಇದೆ" },
  out_better: { en: "Better", hi: "बेहतर है", kn: "ಸುಧಾರಿಸಿದೆ" },
  out_gone: { en: "Gone", hi: "ठीक हो गया", kn: "ಗುಣವಾಗಿದೆ" },
  out_new_problem: { en: "Something new started", hi: "कुछ नया शुरू हुआ", kn: "ಹೊಸದೇನೋ ಶುರುವಾಯಿತು" },

  // ── Vocab: symptom clusters ─────────────────────────────────────────
  cl_respiratory: { en: "Breathing / chest", hi: "साँस / छाती", kn: "ಉಸಿರಾಟ / ಎದೆ" },
  cl_oral: { en: "Mouth", hi: "मुँह", kn: "ಬಾಯಿ" },
  cl_head_neck: { en: "Head and neck", hi: "सिर और गर्दन", kn: "ತಲೆ ಮತ್ತು ಕುತ್ತಿಗೆ" },
  cl_upper_gi: { en: "Stomach / digestion", hi: "पेट / पाचन", kn: "ಹೊಟ್ಟೆ / ಜೀರ್ಣ" },
  cl_lower_gi: { en: "Bowels", hi: "आँतें", kn: "ಕರುಳು" },
  cl_breast: { en: "Breast", hi: "स्तन", kn: "ಸ್ತನ" },
  cl_gynae: { en: "Women's health", hi: "स्त्री स्वास्थ्य", kn: "ಮಹಿಳಾ ಆರೋಗ್ಯ" },
  cl_urological: { en: "Urine / private parts", hi: "पेशाब / गुप्तांग", kn: "ಮೂತ್ರ / ಗುಪ್ತಾಂಗ" },
  cl_systemic: { en: "Whole body (fever, weight, tiredness)", hi: "पूरा शरीर (बुखार, वजन, थकान)", kn: "ಇಡೀ ದೇಹ (ಜ್ವರ, ತೂಕ, ಆಯಾಸ)" },
  cl_skin: { en: "Skin", hi: "त्वचा", kn: "ಚರ್ಮ" },
};

export function translate(key, lang, fallback) {
  const entry = STRINGS[key];
  if (!entry) return fallback ?? key;
  if (lang === "en") return fallback ?? entry.en ?? key;
  return entry[lang] ?? fallback ?? entry.en ?? key;
}

/**
 * Localise a coded value (a provider type, an intervention, an outcome).
 * Unknown codes degrade to their own words rather than to a blank, so a new
 * code added to the ruleset shows as "ct pelvis" and never as nothing.
 */
export function translateCode(prefix, code, lang) {
  if (code == null || code === "") return "";
  const pretty = String(code).replace(/_/g, " ");
  const entry = STRINGS[`${prefix}_${code}`];
  if (!entry) return pretty;
  if (lang === "en") return entry.en ?? pretty;
  return entry[lang] ?? entry.en ?? pretty;
}

const Ctx = createContext({
  lang: "en",
  synced: 0,
  setLang: () => {},
  t: (k, f) => f ?? k,
  tc: (_p, c) => String(c || "").replace(/_/g, " "),
});

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try {
      return localStorage.getItem(KEY) || "en";
    } catch {
      return "en";
    }
  });
  const [saving, setSaving] = useState(false);
  const [synced, setSynced] = useState(0);

  const applyLocal = useCallback((next) => {
    setLangState(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private mode: the choice lasts for this tab only */
    }
    document.documentElement.lang = next;
  }, []);

  const setLang = useCallback(
    async (next) => {
      if (next === lang) return;
      applyLocal(next); // optimistic: the UI must not wait on a round trip
      if ((getSession()?.role || "").toUpperCase() !== "PATIENT") return;
      setSaving(true);
      try {
        await post("/me/language", { language: next });
      } catch {
        /* the local choice stands; the profile syncs on the next change */
      } finally {
        setSaving(false);
        // Two signals, not one, because they are needed at different moments.
        // `lang` flips the app's own furniture the instant you tap, so the
        // control feels answerable. `synced` fires only once the profile has
        // actually changed on the server, and it is what screens re-fetch on
        // - a refetch racing the write returns the OLD language's content and
        // leaves a Kannada nav bar above an English headline.
        setSynced((n) => n + 1);
      }
    },
    [lang, applyLocal]
  );

  // The profile, not this browser, is the source of truth - another device
  // may have changed it. Runs once, and never overrides a change in flight.
  useEffect(() => {
    if ((getSession()?.role || "").toUpperCase() !== "PATIENT") return;
    get("/me/dashboard")
      .then((d) => d?.patient?.language && applyLocal(d.patient.language))
      .catch(() => {});
  }, [applyLocal]);

  const value = useMemo(
    () => ({
      lang,
      synced,
      setLang,
      saving,
      t: (k, f) => translate(k, lang, f),
      tc: (prefix, code) => translateCode(prefix, code, lang),
    }),
    [lang, synced, setLang, saving]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useLang = () => useContext(Ctx);

/**
 * The picker itself. Deliberately a segmented control and not a dropdown:
 * three options fit, and a `<select>` on Android renders the native wheel,
 * which hides the two other scripts behind a tap. Someone who cannot read
 * the current language has to be able to SEE their own script to escape.
 */
export function LanguagePicker({ className = "" }) {
  const { lang, setLang } = useLang();
  return (
    <div
      role="group"
      aria-label="Language"
      className={`inline-flex items-center rounded-full bg-forest-50 p-0.5 ${className}`}
    >
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          type="button"
          onClick={() => setLang(l.code)}
          aria-pressed={lang === l.code}
          title={l.label}
          className={`rounded-full px-2.5 py-1 text-xs font-bold transition ${
            lang === l.code
              ? "bg-forest-900 text-white shadow-sm"
              : "text-forest-700 hover:bg-forest-100"
          }`}
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}
