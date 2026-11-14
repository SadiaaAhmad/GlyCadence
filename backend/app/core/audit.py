from typing import Any
import uuid
from fastapi import Request
from sqlalchemy.orm import Session

from app.models.core import AuditLog


def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    actor_user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    context_metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an immutable audit log entry.

    ``actor_user_id`` and ``patient_id`` are historical UUID references; non-sensitive
    operational context (HTTP method, route path, cohort/role metadata) is stored in
    ``context_metadata`` so audit records remain interpretable after parent deletion.
    """
    request_id = (
        request.headers.get("X-Request-ID") if request else None
    ) or str(uuid.uuid4())
    ip_address = request.client.host if (request and request.client) else None

    meta: dict[str, Any] = {}
    if request is not None:
        meta["http_method"] = request.method
        meta["path"] = request.url.path
    if context_metadata:
        meta.update(context_metadata)

    entry = AuditLog(
        actor_user_id=actor_user_id,
        patient_id=patient_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        ip_address=ip_address,
        context_metadata=meta or None,
    )
    db.add(entry)
    return entry
