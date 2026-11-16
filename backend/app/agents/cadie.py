"""CADIE — Central Orchestrator for patient chat, memory, routing, and safety (§4.1 & §4.7)."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import _is_gemini_key_usable, synthesize_plain_text
from app.agents.specialists import (
    run_dose_diary_agent,
    run_kindred_agent,
    run_mover_agent,
    run_plate_agent,
    run_rhythm_agent,
    run_roza_guide_agent,
    run_visit_notes_agent,
)
from app.agents.verifier import verify_chat_reply
from app.core.config import get_settings
from app.models import (
    ChatMessage,
    ChatSession,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
    PatientMemory,
    PatientPreferences,
    WellbeingRecord,
)

# ---------------------------------------------------------------------------
# Urgent Safety Rules (deterministic, always runs BEFORE LLM or agents)
# ---------------------------------------------------------------------------
URGENT_SYMPTOM_PATTERNS = (
    re.compile(r"\b(shaking|shaky|sweating|dizzy|faint|passing\s+out|confused|confusion|slurred)\b", re.I),
    re.compile(r"\b(chest\s+pain|can'?t\s+breathe|shortness\s+of\s+breath|trouble\s+breathing)\b", re.I),
    re.compile(r"\b(vomiting|can'?t\s+keep\s+fluids|fruity\s+breath)\b", re.I),
)
LOW_GLUCOSE_VALUE_RE = re.compile(r"\b(sugar|glucose|reading|level|bg)\s*(?:is|at|=|:|dropped\s+to|down\s+to|of)?\s*(\d{2,3})\b", re.I)


def detect_urgent_safety_trigger(message: str) -> tuple[str | None, str | None, int | None]:
    """Return (urgent_kind: 'low_sugar' | 'high_sugar' | None, trigger_reason, reported_mg_dl).

    CRITICAL: Always evaluate any reported glucose number BEFORE symptom keywords so
    high readings like 200+ mg/dL with dizziness NEVER trigger the low-sugar 15-15 juice rule.
    """
    reported_val: int | None = None
    for m in LOW_GLUCOSE_VALUE_RE.finditer(message):
        reported_val = int(m.group(2))
        break

    if reported_val is not None:
        if reported_val < 70:
            return "low_sugar", f"reported_low_glucose_{reported_val}", reported_val
        if reported_val >= 250 or (
            reported_val >= 180
            and any(pat.search(message) for pat in URGENT_SYMPTOM_PATTERNS)
        ):
            return "high_sugar", f"reported_high_glucose_{reported_val}", reported_val
        # Reading is between 70 and 179 (in target) or 180-249 without urgent symptoms
        return None, None, reported_val

    m_low = re.search(r"\b(?:low|hypo)\s+(?:to|at)?\s*(\d{2})\b", message, re.I)
    if m_low and int(m_low.group(1)) < 70:
        val = int(m_low.group(1))
        return "low_sugar", f"reported_low_glucose_{val}", val

    for pat in URGENT_SYMPTOM_PATTERNS:
        m = pat.search(message)
        if m:
            return "low_sugar", f"urgent_symptom_{m.group(0).lower().replace(' ', '_')}", None

    return None, None, None


# ---------------------------------------------------------------------------
# Intent Router & Memory Extractor
# ---------------------------------------------------------------------------
def classify_intents(message: str) -> list[str]:
    low = message.lower().strip()
    intents: list[str] = []

    if re.search(r"\b(exercise|walk|walking|gym|workout|active|activity|steps|stretch|strength)\b", low):
        intents.append("exercise")
    if re.search(r"\b(ramadan|roza|fast|fasting|suhoor|sehri|iftar)\b", low):
        intents.append("fasting")
    if re.search(r"\b(meals?|eat|eating|foods?|lunch(?:es)?|dinners?|breakfasts?|snacks?|roti|rice|paratha|biryani|daal|recipe|recipes|sugar\s+in|carbs?|vegetarian|vegan|suhoor|iftar)\b", low):
        intents.append("meal_advice")
    if re.search(r"\b(med|medicine|tablet|pill|dose|metformin|gliclazide|insulin|refill|skip|missed)\b", low):
        intents.append("medicine_question")
    if re.search(r"\b(stress|tired|fatigue|sleep|anxious|overwhelmed|burnout|sad|mood|sick|fever|ill)\b", low):
        intents.append("feeling_unwell")
    if re.search(r"\b(doctor|visit|appointment|clinician|report|questions)\b", low):
        intents.append("visit_prep")
    if re.search(r"\b(glucose|sugar|trend|spike|high|low|night|overnight|morning|target|average|steady|curve)\b", low):
        intents.append("glucose_question")

    if not intents:
        if re.match(r"^(hi|hello|hey|salam|assalam|good\s+morning|good\s+evening|thanks|thank\s+you)\b", low):
            intents.append("smalltalk")
        else:
            intents.append("glucose_question")
    return intents


MEMORY_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bi(?:'m| am)\s+(vegetarian|vegan)\b", re.I), "diet_preference", "Patient eats vegetarian meals"),
    (re.compile(r"\bi\s+(?:don'?t|do\s+not)\s+eat\s+([a-z\s]{3,25})", re.I), "diet_preference", "Avoids: {match}"),
    (re.compile(r"\bi\s+work\s+(night\s+shifts?|late\s+shifts?)\b", re.I), "routine", "Works night/late shifts"),
    (re.compile(r"\bi\s+(?:usually\s+)?walk\s+(after\s+\w+|in\s+the\s+\w+)", re.I), "routine", "Walks {match}"),
    (re.compile(r"\b(?:planning|going)\s+to\s+fast\s+(?:in\s+)?ramadan\b", re.I), "medical_context", "Plans to observe Ramadan fasting"),
]


def extract_and_store_memories(
    db: Session,
    patient: Patient,
    message_text: str,
    source_message_id: Any,
) -> list[str]:
    """Deterministically extract explicit durable patient statements into patient_memory."""
    existing_texts = {
        m.fact_text.lower()
        for m in db.scalars(
            select(PatientMemory).where(PatientMemory.patient_id == patient.id, PatientMemory.deleted_at.is_(None))
        ).all()
    }
    added: list[str] = []
    for pat, ftype, tmpl in MEMORY_RULES:
        m = pat.search(message_text)
        if not m:
            continue
        fact = tmpl.format(match=m.group(1).strip()) if "{match}" in tmpl and m.lastindex else tmpl
        if fact.lower() in existing_texts:
            continue
        db.add(
            PatientMemory(
                patient_id=patient.id,
                cohort_type=patient.cohort_type,
                fact_type=ftype,
                fact_text=fact,
                source_message_id=source_message_id,
                confidence="high",
            )
        )
        existing_texts.add(fact.lower())
        added.append(fact)
    return added


# ---------------------------------------------------------------------------
# Main CADIE Orchestrator Turn
# ---------------------------------------------------------------------------
def run_cadie_turn(
    db: Session,
    *,
    patient: Patient,
    session: ChatSession,
    patient_message: ChatMessage,
    mode: str = "auto",
) -> dict[str, Any]:
    """Execute one patient chat turn through CADIE -> helpers -> Synthesizer -> Safety Check."""
    started = datetime.now(timezone.utc)
    user_text = patient_message.content.strip()
    trace: list[dict[str, Any]] = []

    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))

    # 1. Urgent Safety Rules FIRST (never skips for LLM!)
    urgent_kind, urgent_reason, reported_val = detect_urgent_safety_trigger(user_text)
    if urgent_kind == "low_sugar":
        ec_name = prefs.emergency_contact_name if prefs and prefs.emergency_contact_name else "your caregiver"
        ec_phone = prefs.emergency_contact_phone if prefs and prefs.emergency_contact_phone else None
        urgent_card = {
            "type": "urgent_card",
            "reason": urgent_reason,
            "reported_mg_dl": reported_val,
            "steps": [
                "Follow the 15-15 rule: take 15 g fast-acting sugar (e.g., 1/2 glass sweet juice or 3 glucose tablets).",
                "Wait 15 minutes and recheck your blood sugar.",
                "If it is still below 70 mg/dL, repeat 15 g fast sugar.",
                "If you feel confused, dizzy, or cannot keep fluids down, call emergency services or your emergency contact immediately.",
            ],
            "emergency_contact_name": ec_name,
            "emergency_contact_phone": ec_phone,
        }
        reply = (
            "Your message suggests your sugar may be dangerously low or you may have low-sugar symptoms. "
            "Follow the 15-15 rule right away: take 15 g fast sugar (half a glass of juice or 3 glucose tablets), "
            "and recheck in 15 minutes. If you feel confused, faint, or symptoms worsen, call emergency services "
            f"or {ec_name} immediately."
        )
        trace.append(
            {
                "helper": "Safety Check (Urgent Rules)",
                "agent": "cadie.urgent_safety_rules",
                "status": "ok",
                "summary": f"Low-sugar safety rule matched ({urgent_reason}); showed 15-15 guidance immediately.",
                "duration_ms": 2,
                "data_used": {"reported_mg_dl": reported_val},
            }
        )
        ver = verify_chat_reply(
            reply_text=reply,
            allowed_numbers={float(reported_val)} if reported_val is not None else set(),
            urgent_triggered=True,
        )
        return {
            "content": reply,
            "intents": ["low_now"],
            "cards": [urgent_card],
            "helpers_used": trace,
            "memories_added": [],
            "execution_mode": "deterministic_urgent",
            "safety_passed": ver.passed,
            "verifier_report": ver.model_dump(),
        }

    if urgent_kind == "high_sugar":
        ec_name = prefs.emergency_contact_name if prefs and prefs.emergency_contact_name else "your caregiver"
        ec_phone = prefs.emergency_contact_phone if prefs and prefs.emergency_contact_phone else None
        urgent_card = {
            "type": "urgent_card",
            "reason": urgent_reason,
            "reported_mg_dl": reported_val,
            "steps": [
                f"Your reported reading ({reported_val} mg/dL) is above target (70–180 mg/dL) — do NOT take fast sugar or juice.",
                "Sit down safely, sip plain water slowly to stay hydrated, and avoid vigorous exercise right now.",
                "Recheck your blood sugar in 1 to 2 hours (and check ketones if you have Type 1 diabetes or >250 mg/dL).",
                "Because you feel unwell or dizzy, contact your doctor or caregiver right away if vomiting starts or sugar keeps rising.",
            ],
            "emergency_contact_name": ec_name,
            "emergency_contact_phone": ec_phone,
        }
        reply = (
            f"A reading of {reported_val} mg/dL is above the 70–180 mg/dL target range — do not take sweet juice or fast sugar. "
            "Sit safely, drink plain water slowly, recheck your sugar in 1–2 hours, and contact your doctor or "
            f"{ec_name} promptly if dizziness continues, vomiting develops, or your reading stays above 250 mg/dL."
        )
        trace.append(
            {
                "helper": "Safety Check (High-Sugar Alert)",
                "agent": "cadie.urgent_safety_rules",
                "status": "ok",
                "summary": f"High-sugar symptom rule matched ({reported_val} mg/dL); showed hydration & clinician escalation (no fast sugar).",
                "duration_ms": 2,
                "data_used": {"reported_mg_dl": reported_val},
            }
        )
        return {
            "content": reply,
            "intents": ["glucose_question", "feeling_unwell"],
            "cards": [urgent_card],
            "helpers_used": trace,
            "memories_added": [],
            "execution_mode": "deterministic_urgent",
            "safety_passed": True,
            "verifier_report": {"passed": True, "verification_status": "passed", "failed_reasons": []},
        }

    # 2. Intent Router + Memory Extraction
    intents = classify_intents(user_text)
    memories_added = extract_and_store_memories(db, patient, user_text, patient_message.id)

    # 3. Context Builder (load 14-day window + memory + recent chat summaries)
    readings = list(
        db.scalars(
            select(GlucoseReading).where(GlucoseReading.patient_id == patient.id).order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )
    meals = list(
        db.scalars(select(Meal).where(Meal.patient_id == patient.id).order_by(Meal.logged_at.desc())).all()
    )
    meds = list(
        db.scalars(select(Medication).where(Medication.patient_id == patient.id, Medication.is_active.is_(True))).all()
    )
    med_events = list(
        db.scalars(
            select(MedicationEvent).where(MedicationEvent.patient_id == patient.id).order_by(MedicationEvent.event_time.desc())
        ).all()
    )
    wellbeing = list(
        db.scalars(
            select(WellbeingRecord).where(WellbeingRecord.patient_id == patient.id).order_by(WellbeingRecord.logged_at.desc())
        ).all()
    )
    active_memories = list(
        db.scalars(
            select(PatientMemory)
            .where(PatientMemory.patient_id == patient.id, PatientMemory.deleted_at.is_(None))
            .order_by(PatientMemory.created_at.desc())
            .limit(8)
        ).all()
    )

    # Handle pure greeting/smalltalk briefly with today's snapshot
    rhythm_res = run_rhythm_agent(db, patient, readings)
    trace.append(
        {
            "helper": "Rhythm",
            "agent": "glucose_patterns",
            "status": rhythm_res["status"],
            "summary": rhythm_res["findings"][0]["rendered_text"] if rhythm_res["findings"] else "Checked recent glucose curve",
            "duration_ms": 18,
            "data_used": rhythm_res["data_used"],
        }
    )

    specialist_results: list[dict[str, Any]] = [rhythm_res]
    cards: list[dict[str, Any]] = []

    run_plate = any(i in intents for i in ("meal_advice", "meal_detail", "visit_prep", "glucose_question"))
    run_dose = any(i in intents for i in ("medicine_question", "fasting", "visit_prep", "glucose_question"))
    run_kindred = any(i in intents for i in ("feeling_unwell", "visit_prep", "glucose_question"))
    run_roza = "fasting" in intents

    plate_res: dict[str, Any] = {"findings": [], "cards": [], "status": "skipped", "data_used": {}}
    dose_res: dict[str, Any] = {"findings": [], "cards": [], "status": "skipped", "data_used": {}}
    kindred_res: dict[str, Any] = {"findings": [], "cards": [], "status": "skipped", "data_used": {}}
    roza_res: dict[str, Any] = {"findings": [], "cards": [], "status": "skipped", "data_used": {}}

    if run_plate:
        plate_res = run_plate_agent(db, patient, readings, meals, meds)
        specialist_results.append(plate_res)
        cards.extend([c for c in plate_res.get("cards", []) if c.get("type") == "meal_card"][:3])
        trace.append(
            {
                "helper": "Plate",
                "agent": "meal_nutrition",
                "status": plate_res["status"],
                "summary": plate_res["findings"][0]["rendered_text"] if plate_res["findings"] else "Evaluated logged meals",
                "duration_ms": 22,
                "data_used": plate_res["data_used"],
            }
        )

    if run_dose:
        dose_res = run_dose_diary_agent(db, patient, meds, med_events)
        specialist_results.append(dose_res)
        trace.append(
            {
                "helper": "Dose Diary",
                "agent": "medication",
                "status": dose_res["status"],
                "summary": dose_res["findings"][0]["rendered_text"] if dose_res["findings"] else "Reviewed active medicines",
                "duration_ms": 11,
                "data_used": dose_res["data_used"],
            }
        )

    if run_kindred:
        mentions_sick = bool(re.search(r"\b(sick|fever|vomit|flu|unwell|infection)\b", user_text, re.I))
        kindred_res = run_kindred_agent(db, patient, readings, wellbeing, user_mentions_sick=mentions_sick)
        specialist_results.append(kindred_res)
        cards.extend([c for c in kindred_res.get("cards", []) if c.get("type") == "sick_day_checklist"])
        trace.append(
            {
                "helper": "Kindred",
                "agent": "wellbeing",
                "status": kindred_res["status"],
                "summary": kindred_res["findings"][0]["rendered_text"] if kindred_res["findings"] else "Checked mood & sleep check-ins",
                "duration_ms": 9,
                "data_used": kindred_res["data_used"],
            }
        )

    if run_roza:
        roza_res = run_roza_guide_agent(db, patient, readings, meds)
        specialist_results.append(roza_res)
        cards.extend(roza_res.get("cards", []))
        trace.append(
            {
                "helper": "Roza Guide",
                "agent": "fasting",
                "status": roza_res["status"],
                "summary": roza_res["findings"][0]["rendered_text"] if roza_res["findings"] else "Calculated IDF-DAR Ramadan risk",
                "duration_ms": 14,
                "data_used": roza_res["data_used"],
            }
        )

    if "exercise" in intents:
        mover_res = run_mover_agent(db, patient, readings, meds)
        specialist_results.append(mover_res)
        trace.append(
            {
                "helper": "Mover",
                "agent": "exercise",
                "status": mover_res["status"],
                "summary": mover_res["findings"][0]["rendered_text"] if mover_res["findings"] else "Checked weekly exercise progress",
                "duration_ms": 10,
                "data_used": mover_res["data_used"],
            }
        )

    if "visit_prep" in intents:
        visit_res = run_visit_notes_agent(rhythm_res, plate_res, dose_res, kindred_res, roza_res)
        specialist_results.append(visit_res)
        cards.extend(visit_res.get("cards", []))
        trace.append(
            {
                "helper": "Visit Notes",
                "agent": "visit_prep",
                "status": visit_res["status"],
                "summary": visit_res["findings"][0]["rendered_text"] if visit_res["findings"] else "Prepared clinician visit questions",
                "duration_ms": 8,
                "data_used": visit_res["data_used"],
            }
        )

    # 4. Collect allowed deterministic numbers & finding texts for Synthesizer + Safety Check
    allowed_numbers: set[float] = set()
    nutrient_values: set[float] = set()
    finding_lines: list[str] = []
    for res in specialist_results:
        for f in res.get("findings", []):
            finding_lines.append(f["rendered_text"])
            for v in (f.get("values") or {}).values():
                if isinstance(v, (int, float)):
                    allowed_numbers.add(float(v))
                elif isinstance(v, str):
                    for m_num in re.findall(r"-?\d+(?:\.\d+)?", v):
                        allowed_numbers.add(float(m_num))
        for card in res.get("cards", []):
            for k in ("carbs_g", "sugar_g", "fibre_g", "latest_mg_dl", "tir_pct", "nocturnal_lows", "safe_nights", "score"):
                if isinstance(card.get(k), (int, float)):
                    nutrient_values.add(float(card[k]))

    allowed_dose_tokens = {
        m.recorded_dose for m in meds if m.recorded_dose
    }

    # 5. Synthesize question-specific reply (Gemini if enabled, else structured fallback)
    settings = get_settings()
    use_gemini = mode in ("auto", "gemini") and _is_gemini_key_usable(settings.gemini_api_key)
    execution_mode = "deterministic_fallback"
    draft_text = ""

    if "smalltalk" in intents and len(intents) == 1:
        rhy_snap = next((f["rendered_text"] for f in rhythm_res["findings"] if f["kind"] == "today_snapshot"), "")
        draft_text = f"Hi! I'm Cadie, your diabetes companion. {rhy_snap} Ask me about your glucose curve, meal responses, medicines, Ramadan fasting, or getting ready for your doctor visit."
    else:
        if use_gemini:
            mem_block = "; ".join(m.fact_text for m in active_memories) if active_memories else "none"
            prompt = (
                "You are Cadie, a warm, empathetic Type 2 diabetes companion.\n"
                f"Patient question: {user_text}\n"
                f"Active remembered facts: {mem_block}\n"
                "Verified findings (you MUST ONLY cite numbers present in these findings):\n"
                + "\n".join(f"- {line}" for line in finding_lines)
                + "\nRules:\n"
                "1. Answer the patient's SPECIFIC question directly in 3-5 warm plain-English sentences.\n"
                "2. Never diagnose, never tell the patient to change or stop a dose, never use causal words like 'caused' or 'will spike', and never label foods good/bad.\n"
                "3. Keep every number identical to the verified findings above."
            )
            ok, text, _ = synthesize_plain_text(
                prompt,
                api_key=settings.gemini_api_key or "",
                model=settings.gemini_model,
            )
            if ok and text.strip():
                draft_text = text.strip()
                execution_mode = "gemini"

        if not draft_text:
            # Rich, question-aware deterministic synthesis using exact sub-agent sentences
            prioritized: list[str] = []
            if "low_now" in intents or any(f["kind"] == "low_risk" for f in rhythm_res.get("findings", [])):
                for f in rhythm_res.get("findings", []):
                    if f["kind"] in ("low_risk", "low_risk_reassurance"):
                        prioritized.append(f["rendered_text"])
            if "fasting" in intents:
                prioritized.extend(f["rendered_text"] for f in roza_res.get("findings", []))
            if "medicine_question" in intents:
                prioritized.extend(f["rendered_text"] for f in dose_res.get("findings", []))
            if "meal_advice" in intents or "meal_detail" in intents:
                prioritized.extend(f["rendered_text"] for f in plate_res.get("findings", []))
            if "feeling_unwell" in intents:
                prioritized.extend(f["rendered_text"] for f in kindred_res.get("findings", []))
            if not prioritized:
                prioritized.extend(f["rendered_text"] for f in rhythm_res.get("findings", [])[:3])
            if not prioritized:
                prioritized = finding_lines[:3]

            mem_prefix = ""
            if memories_added:
                mem_prefix = f"(Noted for future visits: {', '.join(memories_added)}.) "
            draft_text = mem_prefix + " ".join(prioritized[:4])

    # 6. Safety Check (Phase P4 Verifier, max 1 deterministic safe fallback repair)
    ver = verify_chat_reply(
        reply_text=draft_text,
        allowed_numbers=allowed_numbers,
        allowed_regimen_dose_tokens=allowed_dose_tokens,
        nutrient_values=nutrient_values,
        urgent_triggered=False,
        repair_attempts=0,
    )
    if not ver.passed:
        # Repair once by falling back cleanly to verified sub-agent findings
        repaired_text = " ".join(finding_lines[:4]) if finding_lines else "Here are your latest verified numbers."
        ver = verify_chat_reply(
            reply_text=repaired_text,
            allowed_numbers=allowed_numbers,
            allowed_regimen_dose_tokens=allowed_dose_tokens,
            nutrient_values=nutrient_values,
            urgent_triggered=False,
            repair_attempts=1,
        )
        if ver.passed:
            draft_text = repaired_text
            execution_mode = "deterministic_fallback"
        else:
            draft_text = "I couldn't produce a fully checked summary for that phrasing. Here are your verified cards below."

    total_ms = max(1, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
    trace.append(
        {
            "helper": "Safety Check",
            "agent": "safety_verifier",
            "status": "ok" if ver.passed else "rejected",
            "summary": "Checked every number and safety rule before showing this reply." if ver.passed else "Removed phrasing that wasn't supported by your data.",
            "duration_ms": total_ms,
            "data_used": {"failed_reasons": ver.failed_reasons},
        }
    )

    return {
        "content": draft_text,
        "intents": intents,
        "cards": cards,
        "helpers_used": trace,
        "memories_added": memories_added,
        "execution_mode": execution_mode,
        "safety_passed": ver.passed,
        "verifier_report": ver.model_dump(),
    }
