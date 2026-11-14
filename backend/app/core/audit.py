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
) -> AuditLog:
    request_id = (
        request.headers.get("X-Request-ID") if request else None
    ) or str(uuid.uuid4())
    ip_address = request.client.host if (request and request.client) else None

    entry = AuditLog(
        actor_user_id=actor_user_id,
        patient_id=patient_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
