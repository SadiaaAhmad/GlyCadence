from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.verifier import verify_chat_reply
from app.core.database import get_engine
from app.main import app
from app.models import AuditLog, Patient
from app.services.synthetic_seed import ensure_v2_demo_environment


def test_p2_chat_history_memory_and_urgent_safety_rules() -> None:
    engine = get_engine()
    assert engine is not None
    with Session(bind=engine) as db:
        p1, _ = ensure_v2_demo_environment(db)
        p1_id = p1.id

    with TestClient(app) as client:
        email = f"p2_chat_{p1_id.hex[:8]}@example.com"
        client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        # 1. Create chat session
        s_res = client.post(f"/api/v1/patients/{p1_id}/chat/sessions", json={}, headers=headers)
        assert s_res.status_code == 201
        sid = s_res.json()["id"]

        # 2. Urgent trigger ("my sugar is 55 and I'm shaking") -> zero LLM call, 15-15 urgent card
        u_res = client.post(
            f"/api/v1/patients/{p1_id}/chat/sessions/{sid}/messages",
            json={"content": "my sugar is 55 and I'm shaking", "mode": "deterministic_fallback"},
            headers=headers,
        )
        assert u_res.status_code == 200
        u_json = u_res.json()
        assert u_json["execution_mode"] == "deterministic_urgent"
        assert u_json["cadie_message"]["cards"][0]["type"] == "urgent_card"
        assert "15-15" in u_json["cadie_message"]["content"]

        # Clean any stale vegetarian memory from prior test runs so extraction is tested freshly
        for existing_m in client.get(f"/api/v1/patients/{p1_id}/memory", headers=headers).json():
            if "vegetarian" in existing_m["fact_text"].lower():
                client.delete(f"/api/v1/patients/{p1_id}/memory/{existing_m['id']}", headers=headers)

        # 3. Normal question + durable memory extraction ("I'm vegetarian")
        m_res = client.post(
            f"/api/v1/patients/{p1_id}/chat/sessions/{sid}/messages",
            json={"content": "Which lunches kept my glucose steady? Also I'm vegetarian", "mode": "deterministic_fallback"},
            headers=headers,
        )
        assert m_res.status_code == 200
        m_json = m_res.json()
        assert "meal_advice" in m_json["patient_message"]["intents"]
        assert m_json["cadie_message"]["safety_passed"] is True
        assert any("vegetarian" in mem.lower() for mem in m_json["memories_added"])
        assert len(m_json["helpers_used"]) >= 3

        # 4. History persists across list/reload
        hist = client.get(f"/api/v1/patients/{p1_id}/chat/sessions/{sid}/messages", headers=headers)
        assert hist.status_code == 200
        assert len(hist.json()) >= 4

        # 5. Memory list & delete
        mems = client.get(f"/api/v1/patients/{p1_id}/memory", headers=headers)
        assert mems.status_code == 200
        veg_mem = next((m for m in mems.json() if "vegetarian" in m["fact_text"].lower()), None)
        assert veg_mem is not None
        d_res = client.delete(f"/api/v1/patients/{p1_id}/memory/{veg_mem['id']}", headers=headers)
        assert d_res.status_code == 204
        mems_after = client.get(f"/api/v1/patients/{p1_id}/memory", headers=headers).json()
        assert all(m["id"] != veg_mem["id"] for m in mems_after)

        # 6. Audit logs must NOT contain raw chat free text
        with Session(bind=engine) as db:
            logs = list(db.scalars(select(AuditLog).where(AuditLog.patient_id == p1_id, AuditLog.resource_type == "chat_turn")).all())
            assert len(logs) >= 1
            for l in logs:
                meta_str = str(l.context_metadata or {})
                assert "vegetarian" not in meta_str
                assert "message_sha256" in meta_str


def test_p3_all_care_tool_agents_and_p6_visit_report() -> None:
    engine = get_engine()
    assert engine is not None
    with Session(bind=engine) as db:
        p1, _ = ensure_v2_demo_environment(db)
        p1_id = p1.id

    with TestClient(app) as client:
        email = f"p3_tools_{p1_id.hex[:8]}@example.com"
        client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        ov = client.get(f"/api/v1/patients/{p1_id}/overview", headers=headers)
        assert ov.status_code == 200
        assert ov.json()["hero"]["latest_mg_dl"] is not None

        med = client.get(f"/api/v1/patients/{p1_id}/medicines/summary", headers=headers)
        assert med.status_code == 200
        assert len(med.json()["medications"]) >= 2
        assert any(m["hypo_risk"] is True for m in med.json()["medications"])
        assert "non-adher" not in str(med.json()).lower()

        wb = client.get(f"/api/v1/patients/{p1_id}/wellbeing/summary", headers=headers)
        assert wb.status_code == 200
        assert len(wb.json()["checkins"]) >= 8

        dds = client.post(
            f"/api/v1/patients/{p1_id}/wellbeing/dds2",
            json={"feeling_overwhelmed_1_to_6": 4, "failing_routine_1_to_6": 4},
            headers=headers,
        )
        assert dds.status_code == 200
        assert dds.json()["elevated_distress"] is True

        roza = client.get(f"/api/v1/patients/{p1_id}/fasting/plan", headers=headers)
        assert roza.status_code == 200
        assert roza.json()["roza"]["cards"][0]["risk_tier"] in ("low", "moderate", "high")

        vr = client.get(f"/api/v1/patients/{p1_id}/visit-report", headers=headers)
        assert vr.status_code == 200
        assert 3 <= len(vr.json()["questions"]) <= 5
        assert all("why" in q for q in vr.json()["questions"])

        vr_html = client.get(f"/api/v1/patients/{p1_id}/visit-report?format=html", headers=headers)
        assert vr_html.status_code == 200
        assert "GlyCadence Clinician Visit Report" in vr_html.text


def test_p4_verify_chat_reply_safety_extensions() -> None:
    bad_num = verify_chat_reply(
        reply_text="Your average glucose is 999 mg/dL today.",
        allowed_numbers={132.0},
    )
    assert not bad_num.passed
    assert "numeric_ungrounded" in bad_num.failed_reasons

    bad_dose = verify_chat_reply(
        reply_text="You should increase 80 mg Gliclazide to 160 mg tomorrow.",
        allowed_numbers={80.0, 160.0},
        allowed_regimen_dose_tokens={"80 mg"},
    )
    assert not bad_dose.passed
    assert "medication_dose_unsafe" in bad_dose.failed_reasons or "prescriptive_overclaim" in bad_dose.failed_reasons

    bad_food = verify_chat_reply(
        reply_text="Aloo paratha is a bad food that caused your sugar spike.",
        allowed_numbers=set(),
    )
    assert not bad_food.passed
    assert "judgmental_food_wording" in bad_food.failed_reasons
    assert "causal_overclaim" in bad_food.failed_reasons

    bad_urgent = verify_chat_reply(
        reply_text="Drink some water and lie down.",
        allowed_numbers=set(),
        urgent_triggered=True,
    )
    assert not bad_urgent.passed
    assert "missing_urgent_guidance" in bad_urgent.failed_reasons

    good = verify_chat_reply(
        reply_text="Your latest reading was 132 mg/dL and average rise after chana daal was 38 mg/dL.",
        allowed_numbers={132.0, 38.0},
    )
    assert good.passed


def test_high_sugar_200_dizzy_never_recommends_fast_sugar_and_mover_exercise_agent() -> None:
    from app.agents.cadie import detect_urgent_safety_trigger

    kind, _, val = detect_urgent_safety_trigger("idk i feel so dizzy, my sugar is 200")
    assert kind == "high_sugar"
    assert val == 200

    kind_low, _, val_low = detect_urgent_safety_trigger("feeling shaky sugar is 55")
    assert kind_low == "low_sugar"
    assert val_low == 55

    with TestClient(app) as client:
        email = "personal_isolated_test@example.com"
        client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        # Personal app_user profile auto-created and listed first
        pts = client.get("/api/v1/patients", headers=headers).json()
        assert len(pts) >= 1
        assert pts[0]["cohort_type"] == "app_user"
        pid = pts[0]["id"]

        # Test chat with 200 + dizzy
        sid = client.post(f"/api/v1/patients/{pid}/chat/sessions", json={}, headers=headers).json()["id"]
        c_res = client.post(
            f"/api/v1/patients/{pid}/chat/sessions/{sid}/messages",
            json={"content": "idk i feel so dizzy, my sugar is 200", "mode": "deterministic_fallback"},
            headers=headers,
        ).json()
        reply_lower = c_res["cadie_message"]["content"].lower()
        assert "do not take sweet juice or fast sugar" in reply_lower
        assert "15-15" not in reply_lower

        # Test Mover Exercise Agent + Logging
        ex_log = client.post(
            f"/api/v1/patients/{pid}/exercise/log",
            json={"activity_type": "post_meal_walk", "duration_min": 15, "intensity": "low"},
            headers=headers,
        )
        assert ex_log.status_code == 200
        ex_plan = client.get(f"/api/v1/patients/{pid}/exercise/plan", headers=headers)
        assert ex_plan.status_code == 200
        assert ex_plan.json()["mover"]["cards"][0]["weekly_minutes"] >= 15


def test_daily_pulse_medicines_wellbeing_meals_and_profile_update() -> None:
    with TestClient(app) as client:
        email = "daily_pulse_user@example.com"
        client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        pid = client.get("/api/v1/patients", headers=headers).json()[0]["id"]

        # 1. Daily Pulse & verify Sensor Graph + Overview update immediately
        dp = client.post(
            f"/api/v1/patients/{pid}/daily-pulse",
            json={"slot": "morning", "glucose_mg_dl": 148, "meds_taken_status": "taken", "feeling_note": "Feeling energetic after walk"},
            headers=headers,
        )
        assert dp.status_code == 200
        assert dp.json()["slot"] == "morning"
        assert dp.json()["glucose_mg_dl"] == 148

        gl_res = client.get(f"/api/v1/patients/{pid}/glucose/readings?days=1", headers=headers)
        assert gl_res.status_code == 200
        assert gl_res.json()["latest_glucose_mg_dl"] == 148.0

        # 2. Add Medicine & Check Summary Recommendations + Disclaimer
        med_add = client.post(
            f"/api/v1/patients/{pid}/medicines/add",
            json={
                "medication_name": "Metformin XR",
                "drug_class": "Biguanide",
                "recorded_dose": "500 mg",
                "prescribed_schedule": "with dinner",
                "units_on_hand": 30,
            },
            headers=headers,
        )
        assert med_add.status_code == 200
        med_sum = client.get(f"/api/v1/patients/{pid}/medicines/summary", headers=headers)
        assert med_sum.status_code == 200
        ms = med_sum.json()
        assert any(m["name"] == "Metformin XR" for m in ms["medications"])
        assert len(ms["agent_recommendations"]) >= 1
        assert "doctor" in ms["safety_disclaimer"].lower()

        # 3. Wellbeing Chat & Doctor Visit Report
        wb = client.post(
            f"/api/v1/patients/{pid}/wellbeing/chat",
            json={"message": "Feeling tired and stressed about sugar today", "mode": "deterministic_fallback"},
            headers=headers,
        )
        assert wb.status_code == 200
        assert wb.json()["saved_to_memory"] is True
        assert wb.json()["reply"]

        vr = client.get(f"/api/v1/patients/{pid}/visit-report", headers=headers)
        assert vr.status_code == 200
        vrj = vr.json()
        assert len(vrj["wellbeing_notes"]) >= 1
        assert "weekly_minutes" in vrj["exercise_summary"]

        # 4. Log Meal & Make Recipe From Ingredients
        ml = client.post(
            f"/api/v1/patients/{pid}/meals/log",
            json={"description": "2 egg omelette with 1 whole wheat roti", "meal_type": "breakfast", "carbs_g": 28, "glucose_mg_dl": 135},
            headers=headers,
        )
        assert ml.status_code == 200

        fi = client.post(
            f"/api/v1/patients/{pid}/meals/from-ingredients",
            json={"ingredients_text": "eggs, black pepper , mango ,and carrot", "meal_type": "dinner"},
            headers=headers,
        )
        assert fi.status_code == 200
        fij = fi.json()
        assert "nutrition" in fij
        assert fij["nutrition"]["calories_kcal"] > 0
        assert fij["nutrition"]["carbs_g"] < 45
        steps_joined = " ".join(fij["steps"]).lower()
        assert "oats" not in steps_joined
        assert "atta" not in steps_joined
        assert "besan" not in steps_joined
        assert "suitability_verdict" in fij
        assert len(fij["steps"]) >= 1

        # 5. Update Display Name
        up = client.patch(f"/api/v1/patients/{pid}", json={"display_name": "Sadia Personal"}, headers=headers)
        assert up.status_code == 200
        assert up.json()["display_name"] == "Sadia Personal"
