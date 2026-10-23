"""Audit trail for administrative and workflow-significant actions."""
from __future__ import annotations

from flask import request

from ..extensions import db
from ..models import AuditLog


def log_action(actor, action: str, entity_type: str, entity_id: int | None = None,
               details: str | None = None, commit: bool = True) -> AuditLog:
    """Append an immutable audit entry.

    ``actor`` may be a User or ``None`` for system generated events.
    """
    entry = AuditLog(
        actor_user_id=getattr(actor, "id", None),
        actor_role=getattr(actor, "role", None),
        action=action[:80],
        entity_type=entity_type[:50],
        entity_id=entity_id,
        details=(details or "")[:1000] or None,
        ip_address=_safe_ip(),
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry


def _safe_ip() -> str | None:
    try:
        from ..security import client_ip
        return client_ip()
    except Exception:  # pragma: no cover - outside request context
        return None
