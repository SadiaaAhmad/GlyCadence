from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    bearer_scheme,
    create_access_token,
    generate_refresh_token,
    get_current_user,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.core import User, UserSession
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    existing = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "email_exists", "message": "An account with this email already exists."},
        )

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="patient",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login_user(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid email or password."},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "user_inactive", "message": "User account is inactive."},
        )

    settings = get_settings()
    access_token, jti, access_expires_at = create_access_token(user.id, user.role)
    refresh_token = generate_refresh_token()
    session_expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)

    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        access_jti=jti,
        expires_at=session_expires_at,
    )
    db.add(session)
    record_audit_event(
        db,
        action="login",
        resource_type="user_session",
        actor_user_id=user.id,
        resource_id=jti,
        request=request,
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expires_at,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_session(
    payload: RefreshRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    now = datetime.now(timezone.utc)
    token_hash = hash_token(payload.refresh_token)
    session = db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_refresh_token", "message": "Refresh token is invalid or expired."},
        )

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "user_inactive", "message": "User account is inactive."},
        )

    new_access_token, new_jti, access_expires_at = create_access_token(user.id, user.role)
    new_refresh_token = generate_refresh_token()
    session.access_jti = new_jti
    session.refresh_token_hash = hash_token(new_refresh_token)
    db.commit()

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_at=access_expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_user(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if credentials is None:
        return
    settings = get_settings()
    payload = jwt.decode(
        credentials.credentials,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    jti = str(payload["jti"])
    session = db.execute(
        select(UserSession).where(
            UserSession.user_id == current_user.id,
            UserSession.access_jti == jti,
            UserSession.revoked_at.is_(None),
        )
    ).scalar_one_or_none()

    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        record_audit_event(
            db,
            action="revoke_token",
            resource_type="user_session",
            actor_user_id=current_user.id,
            resource_id=jti,
            request=request,
        )
        db.commit()


@router.get("/me", response_model=UserOut)
def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
