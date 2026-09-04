"""
Seed the live database with the four demo personas.

    py -3.11 -m uvicorn api.main:app --port 8000      (terminal 1)
    py -3.11 demo/seed.py                             (terminal 2)

Why this exists: you cannot type nine months of symptom history on a stage.
The demo has to open on a database that already contains a patient who has
been ignored for six months, because that is the situation the product is
about. Everything below goes in through the public API - the same endpoints
the phone uses - so seeding cannot accidentally create a state the app itself
could never reach.

The admin is the one exception. There is deliberately no admin signup route:
an operations console that anyone on the internet can register for is not an
operations console. It is written straight to the table here.

Accounts created (password for all: aira-demo-2026):

    patient   9000000001   Sunita Devi      42f  Kolar
    patient   9000000002   Ramesh Kumar     52m  Ballari
    patient   9000000003   Lakshmi Bai      34f  Chitradurga
    patient   9000000004   Arun (guardian)   7m  Tumakuru
    doctor    meera@kolarchc.gov.in
    admin     admin@aira.health
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from demo import personas  # noqa: E402

BASE = "http://127.0.0.1:8000"
PASSWORD = "aira-demo-2026"
TODAY = date.today()

# personas.py pins TODAY to a fixed date so the printed demo is reproducible.
# The database must be seeded relative to the real today, or every duration in
# the UI drifts by however long ago that file was written.
SHIFT = (TODAY - personas.TODAY).days


def shift(d: date) -> date:
    return d + timedelta(days=SHIFT)


def _birthday(age: int) -> date:
    """Someone who is `age` today, with a birthday a fortnight ago."""
    try:
        return TODAY.replace(year=TODAY.year - age) - timedelta(days=14)
    except ValueError:  # 29 February
        return TODAY.replace(year=TODAY.year - age, day=28) - timedelta(days=14)


PEOPLE = [
    {
        "key": "sunita",
        "name": "Sunita Devi",
        "phone": "9000000001",
        "language": "kn",
        "village": "Kolar",
        "state": personas.sunita(),
        "note": "nine months of acidity, three antacids, zero tests",
    },
    {
        "key": "ramesh",
        "name": "Ramesh Kumar",
        "phone": "9000000002",
        "language": "hi",
        "village": "Ballari",
        "state": personas.ramesh(),
        "note": "cough treated twice as TB, never an X-ray",
    },
    {
        "key": "lakshmi",
        "name": "Lakshmi Bai",
        "phone": "9000000003",
        "language": "kn",
        "village": "Chitradurga",
        "state": personas.lakshmi(),
        "note": "sixteen days of cough - proves AIRA does not over-alarm",
    },
    {
        "key": "arun",
        "name": "Arun (guardian account)",
        "phone": "9000000004",
        "language": "hi",
        "village": "Tumakuru",
        "state": personas.arun(),
        "note": "forty days of fever, three antibiotics, no blood count",
    },
]


def ensure_admin() -> None:
    from api.db import SessionLocal
    from api.security import hash_password
    from api.tables import Role, User

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "admin@aira.health").first()
        if existing:
            print("  admin already present")
            return
        db.add(
            User(
                role=Role.ADMIN,
                email="admin@aira.health",
                password_hash=hash_password(PASSWORD),
            )
        )
        db.commit()
        print("  admin created  admin@aira.health")
    finally:
        db.close()


def signup_or_login(c: httpx.Client, person: dict) -> dict | None:
    st = person["state"]
    body = {
        "name": person["name"],
        "phone": person["phone"],
        "password": PASSWORD,
        # A real birthday, not age x 365.25 - that rounding lands a 7-year-old
        # on the wrong side of their birthday and the record then reads "6".
        "dob": str(_birthday(st.person.age)),
        "sex": st.person.sex,
        "language": person["language"],
        "village": person["village"],
        "risk_factors": sorted(st.person.risk_factors),
        "bmi": st.person.bmi,
    }
    r = c.post("/auth/signup/patient", json=body)
    if r.status_code < 300:
        return r.json()

    r = c.post("/auth/login", json={"identifier": person["phone"], "password": PASSWORD})
    if r.status_code < 300:
        print(f"  {person['name']:<24} already seeded, skipping history")
        return None
    raise RuntimeError(f"cannot create or log in {person['name']}: {r.status_code} {r.text}")


def load_history(c: httpx.Client, token: str, person: dict) -> dict:
    H = {"Authorization": f"Bearer {token}"}
    st = person["state"]

    for s in st.symptoms:
        c.post(
            "/me/symptoms",
            headers=H,
            json={
                "code": s.code,
                "onset_date": str(shift(s.onset_date)),
                "severity": s.severity_log[0].score if s.severity_log else None,
            },
        ).raise_for_status()

    for e in st.episodes:
        c.post(
            "/me/episodes",
            headers=H,
            json={
                "cluster_id": e.cluster_id,
                "encounter_date": str(shift(e.encounter_date)),
                "provider_type": e.provider_type,
                "intervention_class": e.intervention_class,
                "investigation_ordered": e.investigation_ordered,
                "outcome_at_followup": e.outcome_at_followup,
            },
        ).raise_for_status()

    return c.get("/me/dashboard", headers=H).raise_for_status().json()


def link(c: httpx.Client, patient_token: str, doctor_token: str) -> None:
    """Walk the real consent handshake rather than writing an ACTIVE row.

    The whole privacy argument rests on consent being an artefact the patient
    creates, so seeding must not be allowed to fabricate one.
    """
    P = {"Authorization": f"Bearer {patient_token}"}
    D = {"Authorization": f"Bearer {doctor_token}"}

    pin = c.post("/consent/pin", headers=P).raise_for_status().json()
    req = c.post(
        "/consent/request",
        headers=D,
        json={"aira_code": pin["aira_code"], "pin": pin["pin"], "days": 90},
    ).raise_for_status().json()
    c.post(f"/consent/{req['id']}/heard", headers=P).raise_for_status()
    c.post(
        f"/consent/{req['id']}/decide", headers=P, json={"decision": "allow"}
    ).raise_for_status()


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60.0)
    c.get("/health").raise_for_status()
    print(f"seeding {BASE}  (dates shifted {SHIFT:+d} days to land on today)\n")

    print("admin")
    ensure_admin()

    print("\ndoctor")
    r = c.post(
        "/auth/signup/doctor",
        json={
            "name": "Dr Meera Rao",
            "email": "meera@kolarchc.gov.in",
            "password": PASSWORD,
            "reg_no": "KMC-41127",
            "facility": "Kolar Community Health Centre",
            "specialty": "General Medicine",
        },
    )
    if r.status_code >= 300:
        r = c.post(
            "/auth/login",
            json={"identifier": "meera@kolarchc.gov.in", "password": PASSWORD},
        )
    doc = r.raise_for_status().json()
    print(f"  {doc['display_name']}  meera@kolarchc.gov.in")

    print("\npatients")
    for person in PEOPLE:
        created = signup_or_login(c, person)
        if created is None:
            continue
        dash = load_history(c, created["access_token"], person)
        link(c, created["access_token"], doc["access_token"])
        s = dash["status"]
        print(
            f"  {person['name']:<24} {created['aira_code']}  "
            f"{s['tier']:<8} L{s['ladder_level']}  {s['ladder_code']}"
        )
        print(f"  {'':<24} {person['note']}")

    q = c.get(
        "/clinic/queue", headers={"Authorization": f"Bearer {doc['access_token']}"}
    ).raise_for_status().json()

    print(f"\nclinician queue: {q['count']} patients, {q['high']} HIGH")
    for row in q["patients"]:
        print(
            f"  {row['tier']:<8} L{row['ladder_level']}  {row['name']:<24} "
            f"{row['days_elapsed']:>4}d  ratio {row['duration_ratio']}  "
            f"visits {row['encounters']}  tests {row['investigations']}"
        )

    print("\n" + "=" * 66)
    print("  log in at http://localhost:5173")
    print(f"  patient  9000000001 / {PASSWORD}   (Sunita - the HIGH one)")
    print(f"  doctor   meera@kolarchc.gov.in / {PASSWORD}")
    print(f"  admin    admin@aira.health / {PASSWORD}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.ConnectError:
        print("server not running:  py -3.11 -m uvicorn api.main:app --port 8000")
        sys.exit(1)
