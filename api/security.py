"""
Password hashing, token issue and verification.

argon2id, not bcrypt and certainly not a bare SHA. bcrypt silently truncates
at 72 bytes and has no memory-hardness; argon2id is the current password
hashing competition winner and is what a security reviewer expects to see on
a health record system.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from jose import JWTError, jwt

from .config import get_settings

settings = get_settings()
_ph = PasswordHasher()

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1 - these get read aloud


def hash_password(raw: str) -> str:
    return _ph.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        _ph.verify(hashed, raw)
        return True
    except (VerifyMismatchError, VerificationError):
        return False


def hash_token(raw: str) -> str:
    """Refresh tokens and link PINs are stored hashed. A database dump must
    not hand the attacker working credentials."""
    return hashlib.sha256(raw.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def new_aira_code() -> str:
    """AIRA-XXXX-XXXX. This project's stand-in for an ABHA address.

    Possession of this code grants NOTHING. It only lets someone ask.
    """
    body = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"AIRA-{body[:4]}-{body[4:]}"


def new_link_pin() -> str:
    """Six digits, ten-minute life, three attempts. Read aloud easily over a
    phone by someone who cannot read a screen."""
    return f"{secrets.randbelow(1_000_000):06d}"


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        return None
    if payload.get("typ") != "access":
        return None
    return payload
