import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.core import Patient, User, UserSession

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: uuid.UUID, role: str, jti: str | None = None) -> tuple[str, str, datetime]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    token_jti = jti or str(uuid.uuid4())
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": token_jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded, token_jti, expires_at


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "missing_token", "message": "Authentication credentials required."},
        )

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "jti", "exp"]},
        )
        user_id = uuid.UUID(payload["sub"])
        jti = str(payload["jti"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_token", "message": "Invalid or expired access token."},
        )

    now = datetime.now(timezone.utc)
    active_session = db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.access_jti == jti,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).scalar_one_or_none()

    if active_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "token_revoked", "message": "Session has been revoked or expired."},
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "user_inactive", "message": "User account is inactive or missing."},
        )
    return user


def require_patient_access(
    patient_id: uuid.UUID,
    current_user: User,
    db: Session,
    *,
    write: bool = False,
) -> Patient:
    """
    Enforce patient-level RBAC and cohort isolation:
    - app_user: owner only (read & write)
    - synthetic_demo: read-only for any authenticated user; write forbidden
    - research_participant: read-only for researcher/admin roles; write forbidden
    """
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "patient_not_found", "message": "Patient record not found."},
        )

    if patient.cohort_type == "app_user":
        if patient.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "You do not have access to this patient."},
            )
        return patient

    if patient.cohort_type == "synthetic_demo":
        if write and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "demo_read_only", "message": "Synthetic demo patients are read-only."},
            )
        return patient

    # research_participant
    if current_user.role not in ("researcher", "admin") or write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "research_restricted", "message": "Research participant records are restricted."},
        )
    return patient
