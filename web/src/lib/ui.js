/** Shared display vocabulary. Kept in one file so a tier never renders two
 *  different ways in two different screens. */

export const TIER = {
  HIGH: {
    label: "Needs a doctor now",
    clinical: "HIGH",
    text: "text-tier-high",
    bg: "bg-tier-high",
    soft: "bg-tier-high/10 text-tier-high",
    ring: "#a02a20",
  },
  MODERATE: {
    label: "Worth checking",
    clinical: "MODERATE",
    text: "text-tier-moderate",
    bg: "bg-tier-moderate",
    soft: "bg-tier-moderate/10 text-tier-moderate",
    ring: "#b4700f",
  },
  LOW: {
    label: "Keep watching",
    clinical: "LOW",
    text: "text-tier-low",
    bg: "bg-tier-low",
    soft: "bg-tier-low/10 text-tier-low",
    ring: "#4b7f6d",
  },
};

export const tier = (t) => TIER[t] || TIER.LOW;

export const LADDER = {
  L0_OBSERVED: {
    short: "Observed",
    meaning: "Recorded and being watched. Nothing is stuck yet.",
  },
  L1_REPEAT_PRESENTATION: {
    short: "Repeat visits",
    meaning: "Seen more than once for this, with no test ordered.",
  },
  L2_TREATMENT_REFRACTORY: {
    short: "Treatment failing",
    meaning: "Treated at least twice and it has not resolved.",
  },
  L3_ESCALATE_NOW: {
    short: "Escalate now",
    meaning: "Failing treatment AND getting worse or spreading.",
  },
};

export const ladder = (code) =>
  LADDER[code] || { short: code, meaning: "" };

export const PROVIDER = {
  phc: "Primary health centre",
  chc: "Community health centre",
  private_clinic: "Private clinic",
  chemist: "Chemist / pharmacy",
  district_hospital: "District hospital",
  ayush: "AYUSH practitioner",
  unknown: "Not recorded",
};

export const INTERVENTION = {
  none: "No treatment given",
  antacid: "Antacid",
  antibiotic: "Antibiotic",
  att: "Anti-TB treatment",
  painkiller: "Painkiller",
  vitamin: "Vitamins / tonic",
  other: "Other",
};

export const OUTCOME = {
  unchanged: "No better",
  worse: "Worse",
  resolved: "It went away",
  partial: "A little better",
};

export const pretty = (s) =>
  String(s || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());

export function days(from) {
  const ms = Date.now() - new Date(from).getTime();
  return Math.max(0, Math.floor(ms / 86400000));
}

export function fmtDate(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function fmtDateTime(d) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
