from datetime import datetime, timezone
import hashlib
from typing import Annotated, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.cadie import run_cadie_turn
from app.core.audit import record_audit_event
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import ChatMessage, ChatSession, PatientMemory, User

router = APIRouter(prefix="/patients/{patient_id}", tags=["Chat & Memory"])


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class ChatSessionOut(BaseModel):
    id: str
    patient_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message_preview: str | None = None


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    mode: Literal["auto", "gemini", "deterministic_fallback"] = "auto"


class ChatMessageOut(BaseModel):
    id: str
    session_id: str
    role: Literal["patient", "cadie"]
    content: str
    intents: list[str]
    cards: list[dict]
    safety_passed: bool | None
    created_at: datetime


class ChatTurnResponse(BaseModel):
    session_id: str
    patient_message: ChatMessageOut
    cadie_message: ChatMessageOut
    helpers_used: list[dict]
    memories_added: list[str]
    execution_mode: str
    verifier_report: dict


class MemoryFactOut(BaseModel):
    id: str
    fact_type: str
    fact_text: str
    confidence: str
    created_at: datetime


def _msg_out(m: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=str(m.id),
        session_id=str(m.session_id),
        role="patient" if m.role == "patient" else "cadie",
        content=m.content,
        intents=list(m.intents or []),
        cards=list(m.cards or []),
        safety_passed=m.safety_passed,
        created_at=m.created_at,
    )


@router.get("/chat/sessions", response_model=list[ChatSessionOut])
def list_chat_sessions(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = Query(default=None),
) -> list[ChatSessionOut]:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.patient_id == patient.id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
    )
    out: list[ChatSessionOut] = []
    for s in sessions:
        msgs = list(
            db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == s.id)
                .order_by(ChatMessage.created_at.asc())
            ).all()
        )
        if q:
            ql = q.lower()
            if ql not in s.title.lower() and not any(ql in m.content.lower() for m in msgs):
                continue
        out.append(
            ChatSessionOut(
                id=str(s.id),
                patient_id=str(s.patient_id),
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=len(msgs),
                last_message_preview=msgs[-1].content[:100] if msgs else None,
            )
        )
    return out


@router.post("/chat/sessions", response_model=ChatSessionOut, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    patient_id: uuid.UUID,
    payload: ChatSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    now = datetime.now(timezone.utc)
    sess = ChatSession(
        id=uuid.uuid4(),
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        title=(payload.title or "Conversation with Cadie").strip(),
        created_at=now,
        updated_at=now,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return ChatSessionOut(
        id=str(sess.id),
        patient_id=str(sess.patient_id),
        title=sess.title,
        created_at=sess.created_at,
        updated_at=sess.updated_at,
        message_count=0,
        last_message_preview=None,
    )


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_chat_messages(
    patient_id: uuid.UUID,
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ChatMessageOut]:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    sess = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.patient_id == patient.id))
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    msgs = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == sess.id)
            .order_by(ChatMessage.created_at.asc())
        ).all()
    )
    return [_msg_out(m) for m in msgs]


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatTurnResponse)
def send_chat_message(
    patient_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: ChatMessageCreate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatTurnResponse:
    # Note: write=False allows standard users to chat cleanly with SYNTH-DEMO-001 too,
    # while cohort isolation still blocks non-researchers from research_participant.
    patient = require_patient_access(patient_id, current_user, db, write=False)
    sess = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.patient_id == patient.id))
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    now = datetime.now(timezone.utc)
    p_msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=sess.id,
        role="patient",
        content=payload.content.strip(),
        intents=[],
        cards=[],
        safety_passed=None,
        created_at=now,
    )
    db.add(p_msg)
    db.flush()

    if sess.title == "Conversation with Cadie":
        sess.title = payload.content.strip()[:60]

    turn = run_cadie_turn(db, patient=patient, session=sess, patient_message=p_msg, mode=payload.mode)
    p_msg.intents = turn["intents"]

    c_msg = ChatMessage(
        id=uuid.uuid4(),
        session_id=sess.id,
        role="cadie",
        content=turn["content"],
        intents=turn["intents"],
        cards=turn["cards"],
        safety_passed=turn["safety_passed"],
        created_at=datetime.now(timezone.utc),
    )
    db.add(c_msg)
    sess.updated_at = c_msg.created_at

    # Audit stores only message SHA-256 checksums and IDs — never raw free text or keys
    msg_hash = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    record_audit_event(
        db,
        action="run_investigation",
        resource_type="chat_turn",
        actor_user_id=current_user.id,
        patient_id=patient.id,
        resource_id=str(c_msg.id),
        request=request,
        context_metadata={
            "session_id": str(sess.id),
            "message_sha256": msg_hash,
            "intents": turn["intents"],
            "execution_mode": turn["execution_mode"],
            "safety_passed": turn["safety_passed"],
        },
    )
    db.commit()
    db.refresh(p_msg)
    db.refresh(c_msg)

    return ChatTurnResponse(
        session_id=str(sess.id),
        patient_message=_msg_out(p_msg),
        cadie_message=_msg_out(c_msg),
        helpers_used=turn["helpers_used"],
        memories_added=turn["memories_added"],
        execution_mode=turn["execution_mode"],
        verifier_report=turn["verifier_report"],
    )


@router.get("/memory", response_model=list[MemoryFactOut])
def list_patient_memory(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MemoryFactOut]:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    facts = list(
        db.scalars(
            select(PatientMemory)
            .where(PatientMemory.patient_id == patient.id, PatientMemory.deleted_at.is_(None))
            .order_by(PatientMemory.created_at.desc())
        ).all()
    )
    return [
        MemoryFactOut(
            id=str(f.id),
            fact_type=f.fact_type,
            fact_text=f.fact_text,
            confidence=f.confidence,
            created_at=f.created_at,
        )
        for f in facts
    ]


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_patient_memory(
    patient_id: uuid.UUID,
    memory_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    fact = db.scalar(
        select(PatientMemory).where(
            PatientMemory.id == memory_id,
            PatientMemory.patient_id == patient.id,
            PatientMemory.deleted_at.is_(None),
        )
    )
    if fact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory fact not found")
    fact.deleted_at = datetime.now(timezone.utc)
    db.commit()
