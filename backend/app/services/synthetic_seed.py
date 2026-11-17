"""Idempotent seeder & regenerator for realistic synthetic demo patients (P1).

Ensures:
- 30 curated desi recipes & USDA/PK FoodItems exist.
- SYNTH-DEMO-001 (Amina Khan — Oral T2D: Metformin + Gliclazide) and
  SYNTH-DEMO-002 (Tariq Mahmood — Basal Insulin + Metformin) have:
  * 14 days of continuous 5-minute CGM readings (ending near current UTC time).
  * 30+ logged meals linked to curated recipes via MealFoodLink, all with full
    [t-30m, t+180m] CGM coverage so >= 80% (nearly 100%) compute valid iAUC.
  * Realistic meal-timing & food-response differences + 2 nocturnal lows +
    stress/sleep co-occurrence + starter chat history & patient memory.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    ChatMessage,
    ChatSession,
    FoodItem,
    GlucoseReading,
    Meal,
    MealFoodLink,
    Medication,
    MedicationEvent,
    MedicationStock,
    Patient,
    PatientMemory,
    PatientPreferences,
    Recipe,
    RecipeIngredient,
    WellbeingRecord,
)
from app.services.food_catalog import compute_recipe_nutrition, ensure_food_and_recipe_catalog


def _build_cgm_and_meals_for_patient(
    db: Session,
    patient: Patient,
    recipes: dict[str, Recipe],
    *,
    is_insulin_demo: bool,
    base_end: datetime,
) -> None:
    """Populate 14 days of 5-min CGM readings aligned with 33–36 recipe-linked meals."""
    cohort = patient.cohort_type
    device_id = "cgm_dexcom_demo" if not is_insulin_demo else "cgm_libre_demo"
    # Align start to midnight UTC 14 days ago (so [start, end] covers full days nicely)
    end_dt = base_end.replace(second=0, microsecond=0)
    end_dt = end_dt - timedelta(minutes=end_dt.minute % 5)
    start_dt = end_dt - timedelta(days=14)

    # Pre-fetch recipe nutrition once
    foods_by_id = {f.id: f for f in db.scalars(select(FoodItem)).all()}
    ings_by_recipe: dict[uuid.UUID, list[tuple[float, FoodItem]]] = {}
    for ing in db.scalars(select(RecipeIngredient)).all():
        ings_by_recipe.setdefault(ing.recipe_id, []).append((ing.grams, foods_by_id[ing.food_item_id]))

    # Daily meal templates with distinct glycemic excursion profiles and clock hours (UTC+5 aligned -> UTC)
    # Using local Lahore hours stored in UTC timestamps for clean diurnal visibility:
    meal_rotation = [
        # (slot, recipe_slug, hour, minute, peak_spike_mg_dl)
        ("breakfast", "masala-omelette-1-roti", 8, 15, 28.0),
        ("breakfast", "whole-wheat-paratha-egg", 8, 30, 56.0),
        ("breakfast", "besan-chilla-mint-dahi", 8, 15, 24.0),
        ("lunch", "chana-daal-brown-rice-salad", 13, 15, 38.0),
        ("lunch", "chicken-tikka-roti-raita", 13, 30, 30.0),
        ("lunch", "chicken-biryani-balanced-portion", 13, 45, 62.0),
        ("dinner", "chicken-karahi-1-chapati", 20, 0, 34.0),
        ("dinner", "keema-matar-whole-roti", 20, 15, 36.0),
        ("dinner", "nihari-light-trimmed-roti", 22, 15, 58.0),  # late dinner -> higher rise!
    ]
    if is_insulin_demo:
        meal_rotation = [
            ("breakfast", "kala-chana-breakfast-bowl", 8, 0, 26.0),
            ("breakfast", "oats-almond-cinnamon-porridge", 8, 30, 44.0),
            ("lunch", "palak-paneer-methi-roti", 13, 15, 31.0),
            ("lunch", "rajma-brown-rice-kachumber", 13, 30, 39.0),
            ("dinner", "masala-grilled-fish-salad", 19, 45, 24.0),
            ("dinner", "dal-palak-chapati", 20, 15, 34.0),
        ]

    planned_meals: list[tuple[datetime, str, Recipe, float]] = []
    # Create 3 meals/day for days 1..12 (inside [start_dt + 1d, end_dt - 1d] so full post-meal CGM window exists!)
    for day_offset in range(1, 13):
        day_anchor = (start_dt + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        b_list = [m for m in meal_rotation if m[0] == "breakfast"]
        l_list = [m for m in meal_rotation if m[0] == "lunch"]
        d_list = [m for m in meal_rotation if m[0] == "dinner"]
        for slot_list in (b_list, l_list, d_list):
            slot, slug, hr, mn, spike = slot_list[day_offset % len(slot_list)]
            meal_dt = day_anchor + timedelta(hours=hr, minutes=mn)
            if meal_dt <= end_dt - timedelta(hours=3):
                planned_meals.append((meal_dt, slot, recipes[slug], spike))

    # Persist meals + MealFoodLink rows
    meal_rows: list[Meal] = []
    link_rows: list[MealFoodLink] = []
    for idx, (meal_dt, slot, rec, _) in enumerate(planned_meals):
        nut = compute_recipe_nutrition(ings_by_recipe.get(rec.id, []))
        mid = uuid.uuid4()
        meal_rows.append(
            Meal(
                id=mid,
                patient_id=patient.id,
                cohort_type=cohort,
                logged_at=meal_dt,
                meal_type=slot,
                description=rec.name,
                ingredients=[],
                calories=nut.kcal,
                carbs_g=nut.carbs_g,
                protein_g=nut.protein_g,
                fat_g=nut.fat_g,
                fiber_g=nut.fibre_g,
                cultural_tag="Pakistani",
                photo_ref=rec.image_url,
                source_dataset="synthetic_demo",
                idempotency_key=f"synth-v2-{patient.external_id}-meal-{idx}",
            )
        )
        link_rows.append(MealFoodLink(id=uuid.uuid4(), meal_id=mid, recipe_id=rec.id))

    db.bulk_save_objects(meal_rows)
    db.flush()
    db.bulk_save_objects(link_rows)

    # Generate 5-minute CGM readings with diurnal rhythm, week-2 drift, 2 nocturnal lows,
    # poor-sleep morning bump, and meal Gaussian-skewed postprandial bumps
    total_steps = int((end_dt - start_dt).total_seconds() // 300) + 1
    cgm_rows: list[GlucoseReading] = []

    # Poor-sleep days: day offsets 4, 7, 10
    poor_sleep_days = {4, 7, 10}
    # Nocturnal hypo days: days 6 and 9 around 03:30 UTC (low for ~40 min -> <70 mg/dL)
    hypo_windows = [
        (start_dt + timedelta(days=6)).replace(hour=3, minute=35, second=0, microsecond=0),
        (start_dt + timedelta(days=9)).replace(hour=4, minute=0, second=0, microsecond=0),
    ]

    for step in range(total_steps):
        ts = start_dt + timedelta(minutes=5 * step)
        day_num = (ts - start_dt).days
        hour_frac = ts.hour + ts.minute / 60.0

        # Base glucose: ~116 mg/dL + subtle week-2 upward drift (+10 mg/dL) + circadian sine
        baseline = 114.0 if not is_insulin_demo else 110.0
        drift_bump = 10.0 * max(0.0, (day_num - 6) / 7.0)
        diurnal = 8.0 * math.sin((hour_frac - 10.0) * math.pi / 12.0)

        # Morning bump on poor-sleep days (07:00 - 11:00)
        sleep_bump = 17.0 if (day_num in poor_sleep_days and 6.5 <= hour_frac <= 10.5) else 0.0

        # Post-meal excursions peaking ~65 min after logged_at and returning by 180 min
        meal_bump = 0.0
        for m_dt, _, _, spike in planned_meals:
            diff_min = (ts - m_dt).total_seconds() / 60.0
            if 0.0 <= diff_min <= 170.0:
                if diff_min <= 65.0:
                    meal_bump += spike * (diff_min / 65.0)
                else:
                    meal_bump += spike * max(0.0, 1.0 - (diff_min - 65.0) / 105.0)

        # Nocturnal low dip
        hypo_dip = 0.0
        for h_dt in hypo_windows:
            diff_min = (ts - h_dt).total_seconds() / 60.0
            if -20.0 <= diff_min <= 45.0:
                hypo_dip -= 50.0 * math.exp(-((diff_min - 12.0) ** 2) / (2 * 14.0 ** 2))

        noise = ((step * 17) % 9) - 4.0
        glucose = max(55.0, min(265.0, round(baseline + drift_bump + diurnal + sleep_bump + meal_bump + hypo_dip + noise, 1)))

        cgm_rows.append(
            GlucoseReading(
                id=uuid.uuid4(),
                patient_id=patient.id,
                cohort_type=cohort,
                recorded_at=ts,
                raw_timestamp=ts.isoformat(),
                timestamp_semantics="utc_exact",
                timezone_basis="source_confirmed",
                glucose_mg_dl=glucose,
                raw_value=glucose,
                raw_unit="mg/dL",
                reading_type="cgm",
                device_id=device_id,
                sampling_interval_min=5,
                observation_provenance="native",
                source_dataset="synthetic_demo",
                idempotency_key=f"synth-v2-{patient.external_id}-cgm-{step}",
            )
        )

    db.bulk_save_objects(cgm_rows)

    # Medications + MedicationStock + MedicationEvents
    if not is_insulin_demo:
        meds_spec = [
            ("Metformin", "Biguanide", "500 mg", "Twice daily with breakfast and dinner", 28.0, 2.0),
            ("Gliclazide", "Sulfonylurea", "80 mg", "Once daily before breakfast", 12.0, 1.0),
        ]
    else:
        meds_spec = [
            ("Insulin Glargine (Lantus)", "Basal Insulin", "18 units", "Once daily at bedtime (10:00 PM)", 90.0, 18.0),
            ("Metformin", "Biguanide", "1000 mg", "Twice daily with meals", 20.0, 2.0),
        ]

    for m_name, d_class, dose, sched, stock_units, daily_u in meds_spec:
        med = Medication(
            id=uuid.uuid4(),
            patient_id=patient.id,
            cohort_type=cohort,
            medication_name=m_name,
            drug_class=d_class,
            recorded_dose=dose,
            prescribed_schedule=sched,
            is_active=True,
            source_dataset="synthetic_demo",
        )
        db.add(med)
        db.flush()
        db.add(
            MedicationStock(
                id=uuid.uuid4(),
                medication_id=med.id,
                units_on_hand=stock_units,
                daily_units=daily_u,
            )
        )
        for d in range(1, 13):
            ev_dt = (start_dt + timedelta(days=d)).replace(hour=8, minute=0, second=0, microsecond=0)
            status_val = "missed" if (d in (5, 11) and d_class == "Sulfonylurea") else "taken"
            db.add(
                MedicationEvent(
                    id=uuid.uuid4(),
                    patient_id=patient.id,
                    cohort_type=cohort,
                    medication_id=med.id,
                    event_time=ev_dt,
                    status=status_val,
                    event_source="patient_log",
                    source_dataset="synthetic_demo",
                    idempotency_key=f"synth-v2-{patient.external_id}-{m_name}-{d}",
                )
            )

    # 10 days of WellbeingRecord check-ins
    for d in range(2, 12):
        wb_dt = (start_dt + timedelta(days=d)).replace(hour=9, minute=30, second=0, microsecond=0)
        is_rough = d in poor_sleep_days
        db.add(
            WellbeingRecord(
                id=uuid.uuid4(),
                patient_id=patient.id,
                cohort_type=cohort,
                logged_at=wb_dt,
                stress_score=4 if is_rough else 2,
                fatigue_score=4 if is_rough else 2,
                sleep_hours=5.5 if is_rough else 7.3,
                sleep_quality=2 if is_rough else 4,
                illness_flag=False,
                mood_notes="Slept restlessly" if is_rough else "Felt steady after evening walk",
                source_dataset="synthetic_demo",
            )
        )

    # PatientPreferences
    db.add(
        PatientPreferences(
            id=uuid.uuid4(),
            patient_id=patient.id,
            cohort_type=cohort,
            vegetarian=False,
            allergies=[],
            budget_tier="low",
            city="Lahore",
            gentle_mode=False,
            language="en",
            target_low_mg_dl=70.0,
            target_high_mg_dl=180.0,
            emergency_contact_name="Sadia (Caregiver)" if not is_insulin_demo else "Bilal (Son)",
            emergency_contact_phone="+92-300-0000001",
        )
    )

    # PatientMemory facts
    facts = [
        ("diet_preference", "Prefers home-cooked Pakistani meals on a modest daily budget"),
        ("routine", "Usually takes a 15-minute walk after dinner when energy is good"),
        ("medical_context", "Observing Ramadan soon and wants suhoor/iftar guidance to review with doctor"),
    ]
    for ftype, ftext in facts:
        db.add(
            PatientMemory(
                id=uuid.uuid4(),
                patient_id=patient.id,
                cohort_type=cohort,
                fact_type=ftype,
                fact_text=ftext,
                confidence="high",
            )
        )

    # Starter ChatSession + ChatMessage so history drawer isn't empty on day 1
    sess = ChatSession(
        id=uuid.uuid4(),
        patient_id=patient.id,
        cohort_type=cohort,
        title="Weekly glucose & meal check-in",
        created_at=end_dt - timedelta(hours=4),
        updated_at=end_dt - timedelta(hours=4),
    )
    db.add(sess)
    db.flush()
    db.add_all([
        ChatMessage(
            id=uuid.uuid4(),
            session_id=sess.id,
            role="patient",
            content="Which lunches kept my sugar steadiest this past week?",
            intents=["meal_advice"],
            cards=[],
            safety_passed=True,
            created_at=end_dt - timedelta(hours=4),
        ),
        ChatMessage(
            id=uuid.uuid4(),
            session_id=sess.id,
            role="cadie",
            content=(
                "Based on your last 12 days of readings, lunches with grilled chicken tikka + 1 chapati "
                "and chana daal with modest brown rice had smaller rises (~30–38 mg/dL) than biryani portions. "
                "Open Meals to see recipes, exact sugar grams, and your personal curve."
            ),
            intents=["meal_advice"],
            cards=[],
            safety_passed=True,
            created_at=end_dt - timedelta(hours=4) + timedelta(seconds=5),
        ),
    ])


def _reset_patient_observations(db: Session, patient_id: uuid.UUID) -> None:
    db.execute(delete(Meal).where(Meal.patient_id == patient_id))
    db.execute(delete(GlucoseReading).where(GlucoseReading.patient_id == patient_id))
    db.execute(delete(MedicationEvent).where(MedicationEvent.patient_id == patient_id))
    db.execute(delete(Medication).where(Medication.patient_id == patient_id))
    db.execute(delete(WellbeingRecord).where(WellbeingRecord.patient_id == patient_id))
    db.execute(delete(PatientPreferences).where(PatientPreferences.patient_id == patient_id))
    db.execute(delete(PatientMemory).where(PatientMemory.patient_id == patient_id))
    db.execute(delete(ChatSession).where(ChatSession.patient_id == patient_id))
    db.flush()


def ensure_v2_demo_environment(db: Session, *, force_regenerate: bool = False) -> tuple[Patient, Patient]:
    """Ensure food/recipe catalog + enriched SYNTH-DEMO-001 & SYNTH-DEMO-002 exist."""
    recipes = ensure_food_and_recipe_catalog(db)
    now_utc = datetime.now(timezone.utc)

    # 1. SYNTH-DEMO-001 (Sadia Ahmad)
    p1 = db.scalar(
        select(Patient).where(Patient.cohort_type == "synthetic_demo", Patient.external_id == "SYNTH-DEMO-001")
    )
    if p1 is None:
        p1 = Patient(
            id=uuid.uuid4(),
            cohort_type="synthetic_demo",
            external_id="SYNTH-DEMO-001",
            source_dataset="synthetic_demo",
            display_name="Sadia Ahmad (T2D Oral Regimen)",
            diabetes_type="T2D",
            age=54,
            sex="female",
            cultural_cuisine_pref="Pakistani",
            timezone="Asia/Karachi",
            retention_policy="365_days",
        )
        db.add(p1)
        db.flush()
        _build_cgm_and_meals_for_patient(db, p1, recipes, is_insulin_demo=False, base_end=now_utc)
    else:
        if p1.display_name.startswith("Amina Khan"):
            p1.display_name = "Sadia Ahmad (T2D Oral Regimen)"
            db.commit()
        has_link = db.scalar(
            select(MealFoodLink).join(Meal, MealFoodLink.meal_id == Meal.id).where(Meal.patient_id == p1.id)
        )
        if force_regenerate or has_link is None:
            p1.display_name = "Sadia Ahmad (T2D Oral Regimen)"
            p1.timezone = "Asia/Karachi"
            _reset_patient_observations(db, p1.id)
            _build_cgm_and_meals_for_patient(db, p1, recipes, is_insulin_demo=False, base_end=now_utc)

    # 2. SYNTH-DEMO-002 (Tariq Mahmood — Basal Insulin T2D)
    p2 = db.scalar(
        select(Patient).where(Patient.cohort_type == "synthetic_demo", Patient.external_id == "SYNTH-DEMO-002")
    )
    if p2 is None:
        p2 = Patient(
            id=uuid.uuid4(),
            cohort_type="synthetic_demo",
            external_id="SYNTH-DEMO-002",
            source_dataset="synthetic_demo",
            display_name="Tariq Mahmood (T2D Basal Insulin)",
            diabetes_type="T2D",
            age=61,
            sex="male",
            cultural_cuisine_pref="Pakistani",
            timezone="Asia/Karachi",
            retention_policy="365_days",
        )
        db.add(p2)
        db.flush()
        _build_cgm_and_meals_for_patient(db, p2, recipes, is_insulin_demo=True, base_end=now_utc)
    elif force_regenerate:
        _reset_patient_observations(db, p2.id)
        _build_cgm_and_meals_for_patient(db, p2, recipes, is_insulin_demo=True, base_end=now_utc)

    db.commit()
    return p1, p2
