"""
End-to-end smoke test against a running server.

Walks the exact path the stage demo walks, and asserts the security
properties along the way rather than just the happy path:

    doctor cannot see a patient before consent      -> 403
    a valid code with a wrong PIN                   -> 400
    consent request grants nothing until approved   -> 403
    after approval the queue populates
    after revocation access dies on the NEXT call   -> 403

    py -3.11 -m uvicorn api.main:app --port 8000     (terminal 1)
    py -3.11 tests/smoke_api.py                      (terminal 2)
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
OK = "  [ok]"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=30.0)
    suffix = random.randint(100000, 999999)

    print("health")
    h = c.get("/health").raise_for_status().json()
    print(f"{OK} ruleset v{h['ruleset_version']}, {h['symptoms']} symptoms, MySQL {h['mysql'][:6]}")

    # ── signup ───────────────────────────────────────────────────────────
    print("\nsignup")
    pat = c.post(
        "/auth/signup/patient",
        json={
            "name": "Sunita Devi",
            "phone": f"9{suffix}0000"[:10],
            "password": "correct-horse-battery",
            "dob": str(date.today() - timedelta(days=42 * 365)),
            "sex": "female",
            "language": "kn",
            "village": "Kolar",
            "risk_factors": ["tobacco_chewing"],
            "bmi": 21.4,
        },
    ).raise_for_status().json()
    print(f"{OK} patient {pat['display_name']}  code {pat['aira_code']}")

    doc = c.post(
        "/auth/signup/doctor",
        json={
            "name": "Dr Meera Rao",
            "email": f"meera{suffix}@kolarchc.gov.in",
            "password": "another-long-password",
            "reg_no": f"KMC-{suffix}",
            "facility": "Kolar CHC",
            "specialty": "General Medicine",
        },
    ).raise_for_status().json()
    print(f"{OK} doctor {doc['display_name']}")

    P = {"Authorization": f"Bearer {pat['access_token']}"}
    D = {"Authorization": f"Bearer {doc['access_token']}"}

    # ── security: no access before consent ───────────────────────────────
    print("\nsecurity: doctor tries to read the record before asking")
    r = c.get(f"/clinic/patients/{pat['user_id']}", headers=D)
    assert r.status_code == 403, r.status_code
    print(f"{OK} 403 - {r.json()['detail']}")

    # ── clinical history ─────────────────────────────────────────────────
    print("\npatient records nine months of acidity")
    c.post(
        "/me/symptoms",
        headers=P,
        json={
            "code": "dyspepsia",
            "onset_date": str(date.today() - timedelta(days=190)),
            "severity": 3,
        },
    ).raise_for_status()
    c.post(
        "/me/symptoms",
        headers=P,
        json={"code": "weight_loss", "onset_date": str(date.today() - timedelta(days=70))},
    ).raise_for_status()

    for days_ago in (185, 110, 40):
        c.post(
            "/me/episodes",
            headers=P,
            json={
                "cluster_id": "upper_gi",
                "encounter_date": str(date.today() - timedelta(days=days_ago)),
                "provider_type": "private_clinic",
                "intervention_class": "antacid",
                "investigation_ordered": "none",
                "outcome_at_followup": "unchanged",
            },
        ).raise_for_status()

    dash = c.get("/me/dashboard", headers=P).raise_for_status().json()
    print(f"{OK} tier {dash['status']['tier']}  L{dash['status']['ladder_level']}  {dash['status']['ladder_code']}")
    assert dash["status"]["tier"] == "HIGH"
    assert dash["status"]["ladder_level"] >= 2
    print(f"{OK} patient message (kn): {dash['status']['message'][:70]}...")

    # ── consent ──────────────────────────────────────────────────────────
    print("\nconsent")
    pin = c.post("/consent/pin", headers=P).raise_for_status().json()
    print(f"{OK} PIN issued, valid {pin['valid_for_minutes']} min")

    r = c.post(
        "/consent/request",
        headers=D,
        json={"aira_code": pin["aira_code"], "pin": "000000", "days": 90},
    )
    assert r.status_code == 400, r.status_code
    print(f"{OK} wrong PIN rejected - '{r.json()['detail']}' (same message as unknown code)")

    req = c.post(
        "/consent/request",
        headers=D,
        json={"aira_code": pin["aira_code"], "pin": pin["pin"], "days": 90},
    ).raise_for_status().json()
    print(f"{OK} request created, status {req['status']}")
    assert req["status"] == "PENDING"

    r = c.get(f"/clinic/patients/{pat['user_id']}", headers=D)
    assert r.status_code == 403, r.status_code
    print(f"{OK} correct PIN alone still grants nothing - 403")

    notice = c.get(f"/consent/{req['id']}/notice", headers=P).raise_for_status().json()
    print(f"{OK} notice ({notice['language']}): {notice['text'][:80]}...")
    c.post(f"/consent/{req['id']}/heard", headers=P).raise_for_status()

    c.post(
        f"/consent/{req['id']}/decide", headers=P, json={"decision": "allow"}
    ).raise_for_status()
    print(f"{OK} patient allowed")

    # ── doctor view ──────────────────────────────────────────────────────
    print("\ndoctor")
    q = c.get("/clinic/queue", headers=D).raise_for_status().json()
    print(f"{OK} queue: {q['count']} patient(s), {q['high']} HIGH")
    assert q["count"] == 1
    row = q["patients"][0]
    print(
        f"{OK} {row['name']} {row['age']}{row['sex'][0]}  {row['tier']}  L{row['ladder_level']}  "
        f"{row['days_elapsed']}d  ratio {row['duration_ratio']}  "
        f"visits {row['encounters']}  tests {row['investigations']}"
    )
    assert row["investigations"] == 0

    card = c.get(
        f"/clinic/patients/{pat['user_id']}/handoff-card", headers=D
    ).raise_for_status().json()
    print(f"{OK} handoff card: {len(card['history'])} visits, "
          f"{card['the_numbers']['investigations_ever_ordered']} investigations ever ordered")
    print(f"       suggests: {', '.join(card['suggested_investigations'][:3])}")

    ex = c.get(f"/clinic/patients/{pat['user_id']}/explain", headers=D).raise_for_status().json()
    print(f"{OK} explain: decided by {ex['decided_by']}, {len(ex['rules_that_fired'])} rules fired")
    for r_ in ex["rules_that_fired"][:2]:
        print(f"       {r_['rule_id']}  <- {r_['source']} {r_.get('section') or ''}")

    # ── FHIR ─────────────────────────────────────────────────────────────
    print("\nFHIR / ABDM")
    bundle = c.get(
        f"/fhir/Patient/{pat['user_id']}/$everything", headers=D
    ).raise_for_status().json()
    kinds: dict[str, int] = {}
    for e in bundle["entry"]:
        k = e["resource"]["resourceType"]
        kinds[k] = kinds.get(k, 0) + 1
    print(f"{OK} Bundle type={bundle['type']}  {kinds}")
    print(f"{OK} consent tag: {bundle['meta']['tag'][0]['display'][:70]}...")

    fc = c.get(f"/fhir/Consent/{req['id']}", headers=D).raise_for_status().json()
    print(f"{OK} FHIR Consent status={fc['status']} provision={fc['provision']['type']}")

    # ── breaking the loop ────────────────────────────────────────────────
    print("\nclinician orders the test that was never ordered")
    c.post(
        f"/clinic/patients/{pat['user_id']}/episodes",
        headers=D,
        json={
            "cluster_id": "upper_gi",
            "encounter_date": str(date.today()),
            "provider_type": "chc",
            "intervention_class": "none",
            "investigation_ordered": "upper_gi_endoscopy",
            "outcome_at_followup": None,
        },
    ).raise_for_status()
    q2 = c.get("/clinic/queue", headers=D).raise_for_status().json()
    print(f"{OK} investigations now {q2['patients'][0]['investigations']} (was 0)")
    assert q2["patients"][0]["investigations"] == 1

    # ── revocation ───────────────────────────────────────────────────────
    print("\nrevocation")
    c.post(f"/consent/{req['id']}/revoke", headers=P).raise_for_status()
    r = c.get(f"/clinic/patients/{pat['user_id']}", headers=D)
    assert r.status_code == 403, r.status_code
    print(f"{OK} access dead on the very next request - 403")
    q3 = c.get("/clinic/queue", headers=D).raise_for_status().json()
    assert q3["count"] == 0
    print(f"{OK} queue now empty")

    # ── voice ────────────────────────────────────────────────────────────
    print("\nvoice")
    v = c.get("/voice/status", headers=P).raise_for_status().json()
    print(f"{OK} sarvam mode={v['mode']} used {v['live_calls_used']}/{v['live_calls_budget']} credits")
    parsed = c.post(
        "/voice/parse-text",
        headers=P,
        json={"text": "I have had a cough for three weeks and losing weight"},
    ).raise_for_status().json()
    print(f"{OK} parsed -> {[x['code'] for x in parsed['candidates']]}, "
          f"duration {parsed['duration_days']} days")
    assert "cough" in [x["code"] for x in parsed["candidates"]]
    assert parsed["duration_days"] == 21

    print("\n" + "=" * 60)
    print("  ALL SMOKE CHECKS PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.ConnectError:
        print("server not running. start it with:")
        print("  py -3.11 -m uvicorn api.main:app --port 8000")
        sys.exit(1)
