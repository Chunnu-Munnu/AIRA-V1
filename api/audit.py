"""
Append-only audit trail.

Two rules, both enforced outside this file as well:

  1. The application database user is granted INSERT and SELECT on audit_log
     and nothing else. Even a full application compromise cannot erase the
     record of what it did.

  2. Denials are logged as loudly as successes. An audit log that only records
     what worked cannot tell you that someone spent an afternoon guessing
     link PINs.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .tables import AuditLog


def record(
    db: Session,
    *,
    action: str,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    consent_id: str | None = None,
    outcome: str = "ok",
    detail: Any = None,
    request: Request | None = None,
) -> None:
    ip = None
    if request is not None and request.client is not None:
        ip = request.client.host

    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, default=str)

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            consent_id=consent_id,
            outcome=outcome,
            detail=detail,
            ip=ip,
        )
    )
    db.commit()
