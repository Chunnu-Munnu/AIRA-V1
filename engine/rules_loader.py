"""
Loads and validates the four ruleset JSON files.

The rules are DATA, not code. That is the point. A clinician can open
rules/symptoms.json, disagree with a safe window, change the number, bump
ruleset_version, and the behaviour of the whole system changes without a
developer touching Python. You cannot do that with a neural network.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


class RulesetError(RuntimeError):
    pass


class Ruleset:
    # Every patient-facing string must exist in all of these before the
    # server is allowed to start.
    LANGUAGES = ("en", "hi", "kn")

    def __init__(self, rules_dir: Path):
        self.dir = Path(rules_dir)
        if not self.dir.exists():
            raise RulesetError(f"rules directory not found: {self.dir.resolve()}")

        self.symptoms_doc = self._load("symptoms.json")
        self.redflags_doc = self._load("redflags.json")
        self.ladder_doc = self._load("ladder.json")
        self.screening_doc = self._load("screening.json")

        self._validate_versions()

        self.version: str = self.symptoms_doc["ruleset_version"]
        self.symptoms: dict[str, dict] = {
            s["code"]: s for s in self.symptoms_doc["symptoms"]
        }
        self.combinations: list[dict] = self.symptoms_doc.get("combination_rules", [])
        self.red_flags: list[dict] = self.redflags_doc["flags"]
        self.contextual_flags: list[dict] = self.redflags_doc.get("contextual_flags", [])
        self.levels: list[dict] = sorted(
            self.ladder_doc["levels"], key=lambda x: x["level"]
        )
        self.programmes: list[dict] = self.screening_doc["programmes"]
        self.defaults: dict = self.symptoms_doc.get("defaults", {})

        self._validate_references()

    def _load(self, name: str) -> dict:
        path = self.dir / name
        if not path.exists():
            raise RulesetError(f"missing ruleset file: {path}")
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _validate_versions(self) -> None:
        """All four files must declare the same ruleset_version. A mismatch
        means someone edited one file and forgot the others, and any
        assessment stored under that version would be unreplayable."""
        versions = {
            "symptoms.json": self.symptoms_doc.get("ruleset_version"),
            "redflags.json": self.redflags_doc.get("ruleset_version"),
            "ladder.json": self.ladder_doc.get("ruleset_version"),
            "screening.json": self.screening_doc.get("ruleset_version"),
        }
        distinct = set(versions.values())
        if len(distinct) != 1 or None in distinct:
            raise RulesetError(f"ruleset_version mismatch across files: {versions}")

    def _validate_references(self) -> None:
        """Every symptom code referenced anywhere must exist. A typo in a
        combination rule would otherwise silently never fire, which is the
        worst kind of clinical bug: invisible."""
        known = set(self.symptoms)
        problems: list[str] = []

        for flag in self.red_flags:
            if flag["symptom"] not in known:
                problems.append(f"redflag {flag['id']} references unknown symptom {flag['symptom']}")

        for combo in self.combinations:
            when = combo["when"]
            for key in ("any_of", "all_of", "companion_any_of"):
                for code in when.get(key, []):
                    if code not in known:
                        problems.append(
                            f"combination {combo['id']} references unknown symptom {code}"
                        )

        # Patient-facing text must exist in every supported language. A system
        # whose entire premise is "we speak to people in their own language"
        # cannot be allowed to boot with a missing translation and silently
        # fall back to English - so this is a startup failure, not a warning.
        for code, spec in self.symptoms.items():
            for key in ("label", "patient_phrasing"):
                block = spec.get(key)
                if block and not all(l in block for l in self.LANGUAGES):
                    problems.append(f"symptom {code}.{key} is missing a translation")
            for ms in spec.get("milestones", []):
                msg = ms.get("message")
                if not isinstance(msg, dict) or not all(l in msg for l in self.LANGUAGES):
                    problems.append(
                        f"symptom {code} milestone day {ms.get('day')} message "
                        "must be an object with en, hi and kn"
                    )

        for flag in self.red_flags:
            pm = flag.get("patient_message", {})
            if not all(l in pm for l in self.LANGUAGES):
                problems.append(f"red flag {flag['id']} patient_message is missing a translation")

        for lvl in self.levels:
            for key in ("label", "patient_message"):
                if not all(l in lvl.get(key, {}) for l in self.LANGUAGES):
                    problems.append(f"ladder level {lvl['code']}.{key} is missing a translation")

        if problems:
            raise RulesetError("ruleset reference errors:\n  " + "\n  ".join(problems))

    def symptom(self, code: str) -> dict:
        if code not in self.symptoms:
            raise RulesetError(f"unknown symptom code: {code}")
        return self.symptoms[code]

    def safe_window(self, code: str) -> int:
        return int(
            self.symptom(code).get(
                "safe_window_days", self.defaults.get("safe_window_days", 28)
            )
        )

    def level(self, n: int) -> dict:
        for lvl in self.levels:
            if lvl["level"] == n:
                return lvl
        raise RulesetError(f"no ladder level {n}")


@lru_cache(maxsize=4)
def load_ruleset(rules_dir: str = "rules") -> Ruleset:
    return Ruleset(Path(rules_dir))
