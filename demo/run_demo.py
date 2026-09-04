"""Print a full assessment for each demo persona.

    python demo/run_demo.py
    python demo/run_demo.py ramesh
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The Windows console defaults to cp1252 and cannot render Devanagari or
# Kannada. Since AIRA's entire premise is that people are spoken to in their
# own language, a demo that silently crashes on that is not acceptable.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from demo.personas import ALL, TODAY  # noqa: E402
from engine import assess, load_ruleset  # noqa: E402

BAR = "=" * 78
TIER_MARK = {"LOW": "  LOW   ", " MODERATE": "MODERATE", "HIGH": "  HIGH  "}


def show(key: str) -> None:
    title, builder = ALL[key]
    state = builder()
    rules = load_ruleset("rules")
    a = assess(state, as_of=TODAY, rules=rules)

    print(BAR)
    print(f"  {title}")
    print(BAR)
    print(f"  Tier          : {a.tier}")
    print(f"  Ladder        : L{a.ladder_level}  {a.ladder_code}")
    print(f"  Anchor        : {a.anchor_symptom}")
    print(f"  Ruleset       : v{a.ruleset_version}")
    print(f"  Next check-back: {a.next_checkback}")

    if a.features:
        f = a.features
        print("\n  TRAJECTORY FEATURES")
        print(f"    days elapsed        {f['days_elapsed']:>6}   (safe window {f['safe_window_days']})")
        print(f"    duration ratio      {f['duration_ratio']:>6}")
        print(f"    episodes            {f['n_episodes']:>6}")
        print(f"    investigations      {f['n_investigations']:>6}")
        print(f"    failed treatments   {f['n_failed_treatments']:>6}")
        print(f"    severity slope      {f['severity_slope']:>6}   (per 30 days)")
        print(f"    breadth creep       {f['breadth_creep']:>6}")
        print(f"    provider switches   {f['provider_switches']:>6}")

    print("\n  WHY  (every line traces to a rule)")
    for r in a.reasons:
        print(f"    [{r.kind:<11}] {r.rule_id}")
        print(f"                  {r.message_clinician}")

    if a.recommended_investigations:
        print("\n  SUGGESTED INVESTIGATIONS")
        print("    " + ", ".join(a.recommended_investigations))

    if a.screening_available:
        print("\n  SCREENING AVAILABLE (free, separate from the above)")
        for s in a.screening_available:
            print(f"    {s['name']}  -  {s['test']} at {s['where']}")

    print()


if __name__ == "__main__":
    keys = sys.argv[1:] or list(ALL)
    for k in keys:
        if k not in ALL:
            print(f"unknown persona '{k}'. choose from: {', '.join(ALL)}")
            sys.exit(1)
        show(k)
