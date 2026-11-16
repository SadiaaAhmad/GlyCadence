from datetime import timedelta
from statistics import mean
from typing import Annotated, Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import evaluate_meal_responses, resolve_single_device_cgm_points
from app.core.database import get_db
from app.core.security import get_current_user, require_patient_access
from app.models import (
    FoodItem,
    GlucoseReading,
    Meal,
    MealFoodLink,
    Medication,
    Recipe,
    RecipeIngredient,
    User,
)
from app.services.food_catalog import compute_recipe_nutrition, ensure_food_and_recipe_catalog

router = APIRouter(tags=["Meals & Recipes"])


class IngredientOut(BaseModel):
    name: str
    name_ur: str | None = None
    grams: float
    source_reference: str | None = None


class NutritionOut(BaseModel):
    carbs_g: float
    sugar_g: float
    fibre_g: float
    protein_g: float
    fat_g: float
    kcal: float
    estimated_gl: float
    gl_band: str


class RecipeOut(BaseModel):
    id: str
    slug: str
    name: str
    cuisine: str
    slot: str
    cost_tier: str
    prep_min: int
    servings: int
    steps: list[str]
    image_url: str
    image_license: str
    image_is_illustration: bool
    tags: list[str]
    guidance_note: str
    ingredients: list[IngredientOut]
    nutrition: NutritionOut


class PersonalResponsePointOut(BaseModel):
    offset_min: int
    glucose_mg_dl: float


class PersonalMealHistoryOut(BaseModel):
    times_observed: int
    avg_rise_mg_dl: float | None = None
    avg_peak_mg_dl: float | None = None
    avg_baseline_mg_dl: float | None = None
    estimated_return_minutes: int | None = None
    curve_points: list[PersonalResponsePointOut]
    summary_text: str


class MealDetailOut(BaseModel):
    meal_id: str | None = None
    recipe: RecipeOut
    logged_at: str | None = None
    meal_type: str
    recommended_time_window: str
    best_time_reason: str
    personal_history: PersonalMealHistoryOut
    what_it_may_mean: list[str]
    health_education_source: str
    confidence_pct: int = 52
    confidence_label: str = "General nutrition match"


class MealPlanSlotOut(BaseModel):
    slot: str
    suggested_window: str
    reason_chip: str
    recommended_recipes: list[RecipeOut]


class MealPlanResponse(BaseModel):
    patient_id: str
    slots: list[MealPlanSlotOut]


def _serialize_recipe(
    recipe: Recipe,
    ings_by_recipe: dict[uuid.UUID, list[tuple[float, FoodItem]]],
) -> RecipeOut:
    items = ings_by_recipe.get(recipe.id, [])
    nut = compute_recipe_nutrition(items)
    return RecipeOut(
        id=str(recipe.id),
        slug=recipe.slug,
        name=recipe.name,
        cuisine=recipe.cuisine,
        slot=recipe.slot,
        cost_tier=recipe.cost_tier,
        prep_min=recipe.prep_min,
        servings=recipe.servings,
        steps=list(recipe.steps or []),
        image_url=recipe.image_url,
        image_license=recipe.image_license,
        image_is_illustration=recipe.image_is_illustration,
        tags=list(recipe.tags or []),
        guidance_note=recipe.guidance_note,
        ingredients=[
            IngredientOut(
                name=food.name,
                name_ur=food.name_ur,
                grams=grams,
                source_reference=food.source_reference,
            )
            for grams, food in items
        ],
        nutrition=NutritionOut(
            carbs_g=nut.carbs_g,
            sugar_g=nut.sugar_g,
            fibre_g=nut.fibre_g,
            protein_g=nut.protein_g,
            fat_g=nut.fat_g,
            kcal=nut.kcal,
            estimated_gl=nut.estimated_gl,
            gl_band=nut.gl_band,
        ),
    )


def _load_recipe_maps(db: Session) -> tuple[list[Recipe], dict[uuid.UUID, list[tuple[float, FoodItem]]]]:
    ensure_food_and_recipe_catalog(db)
    recipes = list(db.scalars(select(Recipe).order_by(Recipe.slot.asc(), Recipe.name.asc())).all())
    foods = {f.id: f for f in db.scalars(select(FoodItem)).all()}
    ings_by_recipe: dict[uuid.UUID, list[tuple[float, FoodItem]]] = {}
    for ing in db.scalars(select(RecipeIngredient)).all():
        if ing.food_item_id in foods:
            ings_by_recipe.setdefault(ing.recipe_id, []).append((ing.grams, foods[ing.food_item_id]))
    return recipes, ings_by_recipe


def _build_personal_history_for_meals(
    db: Session,
    patient_id: uuid.UUID,
    matching_meals: list[Meal],
) -> PersonalMealHistoryOut:
    if not matching_meals:
        return PersonalMealHistoryOut(
            times_observed=0,
            curve_points=[],
            summary_text="Not logged yet — once you log this meal while wearing a sensor, your personal glucose curve will appear here.",
        )

    readings = list(
        db.scalars(
            select(GlucoseReading)
            .where(GlucoseReading.patient_id == patient_id)
            .order_by(GlucoseReading.recorded_at.asc())
        ).all()
    )
    cgm_points, _, _ = resolve_single_device_cgm_points(readings)
    eval_results = evaluate_meal_responses(
        matching_meals,
        cgm_points,
        allowed_provenances=frozenset({"native", "dataset_documented"}),
    )
    valid_evals = [e for e in eval_results if e.iauc_valid and e.excursion_delta_mg_dl is not None]

    # Build average curve in 15-minute bins from -15 to +180 min
    bins: dict[int, list[float]] = {off: [] for off in range(-15, 181, 15)}
    for m in matching_meals:
        for p in cgm_points:
            diff = (p.recorded_at - m.logged_at).total_seconds() / 60.0
            if -18 <= diff <= 183:
                nearest_bin = int(round(diff / 15.0) * 15)
                if nearest_bin in bins:
                    bins[nearest_bin].append(p.glucose_mg_dl)

    curve = [
        PersonalResponsePointOut(offset_min=off, glucose_mg_dl=round(mean(vals), 1))
        for off, vals in sorted(bins.items())
        if vals
    ]

    if not valid_evals:
        return PersonalMealHistoryOut(
            times_observed=len(matching_meals),
            curve_points=curve,
            summary_text=f"Logged {len(matching_meals)} time(s), but full post-meal sensor coverage was not yet available.",
        )

    avg_rise = round(mean(e.excursion_delta_mg_dl for e in valid_evals if e.excursion_delta_mg_dl is not None), 1)
    avg_peak = round(mean(e.peak_post_meal_glucose_mg_dl for e in valid_evals if e.peak_post_meal_glucose_mg_dl is not None), 1)
    avg_base = round(mean(e.pre_meal_glucose_mg_dl for e in valid_evals if e.pre_meal_glucose_mg_dl is not None), 1)

    # Estimate minutes to return within +15 mg/dL of baseline after peak
    return_min = 120
    if curve:
        peak_pt = max(curve, key=lambda c: c.glucose_mg_dl)
        after_peak = [c for c in curve if c.offset_min > peak_pt.offset_min]
        for c in after_peak:
            if c.glucose_mg_dl <= avg_base + 15.0:
                return_min = c.offset_min
                break
        else:
            return_min = 180

    sign = "+" if avg_rise >= 0 else ""
    summary = (
        f"Across {len(valid_evals)} logged meal(s): average sugar change {sign}{avg_rise:.0f} mg/dL "
        f"(from {avg_base:.0f} to {avg_peak:.0f} mg/dL), returning near baseline in ~{return_min} min."
    )
    return PersonalMealHistoryOut(
        times_observed=len(valid_evals),
        avg_rise_mg_dl=avg_rise,
        avg_peak_mg_dl=avg_peak,
        avg_baseline_mg_dl=avg_base,
        estimated_return_minutes=return_min,
        curve_points=curve,
        summary_text=summary,
    )


@router.get("/recipes", response_model=list[RecipeOut])
def list_recipes(
    db: Annotated[Session, Depends(get_db)],
    slot: str | None = Query(default=None),
    vegetarian: bool | None = Query(default=None),
    budget: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[RecipeOut]:
    recipes, ings_by_recipe = _load_recipe_maps(db)
    out: list[RecipeOut] = []
    for r in recipes:
        if slot and r.slot != slot:
            continue
        if vegetarian is True and "vegetarian" not in (r.tags or []):
            continue
        if budget and budget != "high" and r.cost_tier != budget and not (budget == "medium" and r.cost_tier == "low"):
            continue
        if q and q.lower() not in r.name.lower() and q.lower() not in " ".join(r.tags or []).lower():
            continue
        out.append(_serialize_recipe(r, ings_by_recipe))
    return out


@router.get("/recipes/{recipe_id}", response_model=MealDetailOut)
def get_recipe_detail(
    recipe_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    patient_id: uuid.UUID | None = Query(default=None),
) -> MealDetailOut:
    recipes, ings_by_recipe = _load_recipe_maps(db)
    match = next((r for r in recipes if r.id == recipe_id), None)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    rec_out = _serialize_recipe(match, ings_by_recipe)
    personal = PersonalMealHistoryOut(
        times_observed=0,
        curve_points=[],
        summary_text="Select a patient to inspect personal post-meal history.",
    )
    if patient_id is not None:
        patient = require_patient_access(patient_id, current_user, db, write=False)
        linked_meal_ids = list(
            db.scalars(select(MealFoodLink.meal_id).where(MealFoodLink.recipe_id == match.id)).all()
        )
        matching_meals = list(
            db.scalars(
                select(Meal)
                .where(Meal.patient_id == patient.id, Meal.id.in_(linked_meal_ids))
                .order_by(Meal.logged_at.desc())
            ).all()
        ) if linked_meal_ids else []
        personal = _build_personal_history_for_meals(db, patient.id, matching_meals)

    slot_windows = {
        "breakfast": ("8:00 AM – 9:00 AM", "Fits morning routine alongside breakfast medicines"),
        "lunch": ("1:00 PM – 2:00 PM", "Spacing 4–5 hours after breakfast helps avoid overlapping rises"),
        "dinner": ("7:30 PM – 8:30 PM", "Earlier dinners are associated with steadier overnight glucose"),
        "snack": ("4:30 PM – 5:30 PM", "Bridges afternoon gap without spiking before dinner"),
        "suhoor": ("Before Fajr (pre-dawn)", "Slow-digesting carbs + protein for fasting hours"),
        "iftar": ("At Maghrib (sunset)", "Small portion after water helps limit post-iftar spikes"),
    }
    win, reason = slot_windows.get(match.slot, ("Regular mealtime", "General meal-timing guidance"))

    mean_notes = [
        rec_out.guidance_note,
        f"Computed from ingredients: {rec_out.nutrition.carbs_g}g carbs ({rec_out.nutrition.sugar_g}g sugar, {rec_out.nutrition.fibre_g}g fibre) — {rec_out.nutrition.gl_band} glycaemic load ({rec_out.nutrition.estimated_gl}).",
        "General guidance: Higher-fibre whole foods and pairing carbs with protein/vegetables are generally associated with smaller post-meal glucose rises (no individual outcome guarantee).",
    ]
    return MealDetailOut(
        recipe=rec_out,
        meal_type=match.slot,
        recommended_time_window=win,
        best_time_reason=reason,
        personal_history=personal,
        what_it_may_mean=mean_notes,
        health_education_source="USDA FoodData Central & ADA Standards of Care 2025 (educational nutrition facts, not medical advice)",
        confidence_pct=min(96, 52 + 11 * personal.times_observed) if personal.times_observed > 0 else 52,
        confidence_label=(
            f"{min(96, 52 + 11 * personal.times_observed)}% personal match (based on {personal.times_observed} logged meal(s))"
            if personal.times_observed > 0
            else "52% general match (log this meal once to personalize)"
        ),
    )


@router.get("/patients/{patient_id}/meals/plan", response_model=MealPlanResponse)
def get_patient_meal_plan(
    patient_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MealPlanResponse:
    from app.models import PatientPreferences

    patient = require_patient_access(patient_id, current_user, db, write=False)
    recipes, ings_by_recipe = _load_recipe_maps(db)
    prefs = db.scalar(select(PatientPreferences).where(PatientPreferences.patient_id == patient.id))

    # Evaluate patient's meals & glucose track to personalize slots and recipe ranking
    meals = list(db.scalars(select(Meal).where(Meal.patient_id == patient.id).order_by(Meal.logged_at.desc())).all())
    readings = list(db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == patient.id).order_by(GlucoseReading.recorded_at.asc())).all())
    cgm_points, _, _ = resolve_single_device_cgm_points(readings)
    evals = evaluate_meal_responses(meals, cgm_points, allowed_provenances=frozenset({"native", "dataset_documented"}))
    eval_by_id = {e.meal_id: e for e in evals}

    recent_vals = [float(r.glucose_mg_dl) for r in readings[-14:]]
    latest_val = recent_vals[-1] if recent_vals else None
    avg_val = mean(recent_vals) if recent_vals else None
    has_highs = (latest_val is not None and latest_val >= 180) or (avg_val is not None and avg_val >= 155)
    has_lows = any(v < 70 for v in recent_vals)

    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id, Medication.is_active.is_(True))).all())
    has_sulfo = any("sulfonylurea" in (m.drug_class or "").lower() for m in meds)

    # Dynamic slot reasons tailored to this patient's track
    early_dinners = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour < 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
    late_dinners = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour >= 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
    if early_dinners and late_dinners:
        dinner_reason = f"Your dinners before 9 pm rose +{mean(early_dinners):.0f} mg/dL on average vs +{mean(late_dinners):.0f} mg/dL after 9 pm"
    elif has_highs:
        dinner_reason = f"Recent readings reached {round(latest_val or avg_val or 180)} mg/dL — prioritized lighter, low-GL dinners before 8:30 pm"
    else:
        dinner_reason = "Eating dinner by 8:30 pm leaves 2–3 hours before sleep for steadier nights"

    if has_lows or has_sulfo:
        breakfast_reason = "Steady protein + slow carbs to support morning medicines and prevent mid-morning dips"
        lunch_reason = "Balanced daal/protein + moderate complex carbs for steady afternoon energy"
        snack_reason = "Protein + fibre bridge to prevent late-afternoon drops before dinner"
    elif has_highs:
        breakfast_reason = "Low-sugar, high-protein breakfast to blunt morning rises"
        lunch_reason = "Extra-low glycaemic load lunches paired with fibre to flatten afternoon spikes"
        snack_reason = "Very low-carb, high-fibre snack options that keep post-snack sugar flat"
    else:
        breakfast_reason = "Higher-protein breakfast within 1–2 hours of waking supports steady mornings"
        lunch_reason = "Measured carbs with daal/salad support steady afternoon curves"
        snack_reason = "Light protein/fibre snack bridges the gap to dinner"

    slot_specs = [
        ("breakfast", "8:00 AM – 9:00 AM", breakfast_reason),
        ("lunch", "1:00 PM – 2:00 PM", lunch_reason),
        ("snack", "4:30 PM – 5:30 PM", snack_reason),
        ("dinner", "7:30 PM – 8:30 PM", dinner_reason),
    ]

    def _score_recipe(ro: RecipeOut) -> float:
        if has_highs:
            s = ro.nutrition.estimated_gl * 2.0 + ro.nutrition.sugar_g - ro.nutrition.fibre_g * 0.8
        elif has_lows or has_sulfo:
            s = abs(ro.nutrition.carbs_g - 30.0) * 0.45 - ro.nutrition.protein_g * 0.6 - ro.nutrition.fibre_g * 0.5
        else:
            s = ro.nutrition.estimated_gl - ro.nutrition.protein_g * 0.3 - ro.nutrition.fibre_g * 0.4
        if prefs and prefs.budget_tier == "low" and ro.cost_tier == "low":
            s -= 3.0
        return s

    slots_out: list[MealPlanSlotOut] = []
    for slot_name, win, reason in slot_specs:
        slot_recipes = [
            _serialize_recipe(r, ings_by_recipe)
            for r in recipes
            if r.slot == slot_name and not (prefs and prefs.vegetarian and "vegetarian" not in (r.tags or []))
        ]
        slot_recipes.sort(key=_score_recipe)
        slots_out.append(
            MealPlanSlotOut(
                slot=slot_name,
                suggested_window=win,
                reason_chip=reason,
                recommended_recipes=slot_recipes[:4],
            )
        )

    return MealPlanResponse(patient_id=str(patient.id), slots=slots_out)


@router.get("/patients/{patient_id}/meals/{meal_id}", response_model=MealDetailOut)
def get_patient_meal_detail(
    patient_id: uuid.UUID,
    meal_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MealDetailOut:
    patient = require_patient_access(patient_id, current_user, db, write=False)
    meal = db.scalar(select(Meal).where(Meal.id == meal_id, Meal.patient_id == patient.id))
    if meal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")

    recipes, ings_by_recipe = _load_recipe_maps(db)
    link = db.scalar(select(MealFoodLink).where(MealFoodLink.meal_id == meal.id))
    recipe_obj = next((r for r in recipes if link and r.id == link.recipe_id), None)
    if recipe_obj is None:
        recipe_obj = next((r for r in recipes if r.name.lower() in meal.description.lower()), recipes[0])

    rec_out = _serialize_recipe(recipe_obj, ings_by_recipe)
    # Match all meals with same description or recipe link for personal history
    linked_ids = list(
        db.scalars(select(MealFoodLink.meal_id).where(MealFoodLink.recipe_id == recipe_obj.id)).all()
    )
    same_meals = list(
        db.scalars(
            select(Meal).where(
                Meal.patient_id == patient.id,
                (Meal.id.in_(linked_ids) if linked_ids else (Meal.id == meal.id)),
            )
        ).all()
    )
    if meal.id not in [m.id for m in same_meals]:
        same_meals.append(meal)

    personal = _build_personal_history_for_meals(db, patient.id, same_meals)
    return MealDetailOut(
        meal_id=str(meal.id),
        recipe=rec_out,
        logged_at=meal.logged_at.isoformat(),
        meal_type=meal.meal_type,
        recommended_time_window="8:00–9:00 AM" if meal.meal_type == "breakfast" else ("1:00–2:00 PM" if meal.meal_type == "lunch" else "7:30–8:30 PM"),
        best_time_reason="Based on your observed meal windows and regimen schedule.",
        personal_history=personal,
        what_it_may_mean=[
            rec_out.guidance_note,
            f"Nutrition per portion (computed from ingredients): {rec_out.nutrition.carbs_g}g carbs, {rec_out.nutrition.sugar_g}g sugar, {rec_out.nutrition.fibre_g}g fibre ({rec_out.nutrition.gl_band} GL).",
            "General education: Post-meal glucose peaks commonly occur 45–90 minutes after eating and settle within 2–3 hours.",
        ],
        health_education_source="USDA FoodData Central & ADA Standards of Care 2025",
        confidence_pct=min(96, 52 + 11 * personal.times_observed) if personal.times_observed > 0 else 52,
        confidence_label=(
            f"{min(96, 52 + 11 * personal.times_observed)}% personal match (based on {personal.times_observed} logged meal(s))"
            if personal.times_observed > 0
            else "52% general match (log this meal once to personalize)"
        ),
    )


class LogMealRequest(BaseModel):
    description: str = Field(min_length=2, max_length=255)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"
    recipe_id: str | None = None
    carbs_g: float | None = Field(default=None, ge=0.0, le=300.0)
    glucose_mg_dl: float | None = Field(default=None, ge=25.0, le=600.0)


class CustomIngredientsRequest(BaseModel):
    ingredients_text: str = Field(min_length=2, max_length=400)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = "lunch"


@router.post("/patients/{patient_id}/meals/log")
def log_patient_meal(
    patient_id: uuid.UUID,
    payload: LogMealRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    from datetime import datetime, timezone
    from app.models import User

    patient = require_patient_access(patient_id, current_user, db, write=False)
    now_utc = datetime.now(timezone.utc)
    m = Meal(
        id=uuid.uuid4(),
        patient_id=patient.id,
        cohort_type=patient.cohort_type,
        logged_at=now_utc,
        meal_type=payload.meal_type,
        description=payload.description.strip(),
        ingredients=[],
        carbs_g=payload.carbs_g,
        cultural_tag="Pakistani",
        source_dataset="app_user",
    )
    db.add(m)
    db.flush()
    if payload.recipe_id:
        try:
            rid = uuid.UUID(payload.recipe_id)
            db.add(MealFoodLink(id=uuid.uuid4(), meal_id=m.id, recipe_id=rid))
        except ValueError:
            pass
    if payload.glucose_mg_dl is not None:
        db.add(
            GlucoseReading(
                id=uuid.uuid4(),
                patient_id=patient.id,
                cohort_type=patient.cohort_type,
                recorded_at=now_utc,
                raw_timestamp=now_utc.isoformat(),
                timestamp_semantics="utc_exact",
                timezone_basis="source_confirmed",
                glucose_mg_dl=payload.glucose_mg_dl,
                raw_value=payload.glucose_mg_dl,
                raw_unit="mg/dL",
                reading_type="post_meal",
                observation_provenance="native",
                source_dataset="app_user",
            )
        )
    db.commit()
    return {"status": "logged", "meal_id": str(m.id)}


@router.post("/patients/{patient_id}/meals/from-ingredients")
def create_recipe_from_ingredients(
    patient_id: uuid.UUID,
    payload: CustomIngredientsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Match patient's exact kitchen ingredients against FoodItems or built-in nutrition table, compute exact nutrition, and draft a strict recipe."""
    import re
    from app.agents.llm import _is_gemini_key_usable, synthesize_plain_text
    from app.core.config import get_settings

    patient = require_patient_access(patient_id, current_user, db, write=False)
    ensure_food_and_recipe_catalog(db)
    all_foods = list(db.scalars(select(FoodItem)).all())

    raw_tokens = [
        re.sub(r"^(and|fresh|some|a|an)\s+", "", t.strip().lower()).strip()
        for t in re.split(r"[,;\n]+", payload.ingredients_text)
        if t.strip()
    ]
    tokens = [t for t in raw_tokens if t]

    # Built-in per-100g nutrition + standard home serving (grams) for common kitchen items
    # (grams, carbs_100, sugar_100, fibre_100, protein_100, fat_100, kcal_100, gi)
    BUILTIN_NUTRITION: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
        "egg": (100.0, 1.1, 1.1, 0.0, 12.6, 10.6, 155.0, 0.0),
        "eggs": (100.0, 1.1, 1.1, 0.0, 12.6, 10.6, 155.0, 0.0),
        "black pepper": (2.0, 64.0, 0.6, 25.0, 10.4, 3.3, 251.0, 15.0),
        "pepper": (2.0, 64.0, 0.6, 25.0, 10.4, 3.3, 251.0, 15.0),
        "mango": (80.0, 15.0, 13.7, 1.6, 0.8, 0.4, 60.0, 51.0),
        "carrot": (70.0, 9.6, 4.7, 2.8, 0.9, 0.2, 41.0, 39.0),
        "carrots": (70.0, 9.6, 4.7, 2.8, 0.9, 0.2, 41.0, 39.0),
        "spinach": (100.0, 3.6, 0.4, 2.2, 2.9, 0.4, 23.0, 15.0),
        "tomato": (90.0, 3.9, 2.6, 1.2, 0.9, 0.2, 18.0, 15.0),
        "tomatoes": (90.0, 3.9, 2.6, 1.2, 0.9, 0.2, 18.0, 15.0),
        "onion": (60.0, 9.3, 4.2, 1.7, 1.1, 0.1, 40.0, 15.0),
        "garlic": (6.0, 33.0, 1.0, 2.1, 6.4, 0.5, 149.0, 15.0),
        "cucumber": (100.0, 3.6, 1.7, 0.5, 0.7, 0.1, 15.0, 15.0),
        "chicken": (120.0, 0.0, 0.0, 0.0, 27.0, 3.6, 165.0, 0.0),
        "fish": (120.0, 0.0, 0.0, 0.0, 22.0, 5.0, 135.0, 0.0),
        "yogurt": (100.0, 4.7, 4.7, 0.0, 3.5, 3.3, 61.0, 35.0),
        "paneer": (80.0, 1.2, 1.2, 0.0, 18.3, 20.8, 265.0, 27.0),
        "cheese": (40.0, 1.3, 0.5, 0.0, 25.0, 33.0, 402.0, 27.0),
        "milk": (150.0, 4.8, 5.0, 0.0, 3.4, 3.3, 61.0, 31.0),
        "apple": (120.0, 13.8, 10.4, 2.4, 0.3, 0.2, 52.0, 36.0),
        "banana": (100.0, 22.8, 12.2, 2.6, 1.1, 0.3, 89.0, 51.0),
        "potato": (100.0, 17.5, 0.8, 2.2, 2.0, 0.1, 77.0, 78.0),
        "rice": (100.0, 28.0, 0.1, 0.4, 2.7, 0.3, 130.0, 73.0),
        "oats": (40.0, 66.3, 1.0, 10.6, 16.9, 6.9, 389.0, 55.0),
        "roti": (45.0, 46.0, 1.5, 6.0, 9.0, 3.5, 250.0, 62.0),
        "whole wheat roti": (45.0, 46.0, 1.5, 6.0, 9.0, 3.5, 250.0, 62.0),
        "olive oil": (5.0, 0.0, 0.0, 0.0, 0.0, 100.0, 884.0, 0.0),
        "butter": (5.0, 0.1, 0.1, 0.0, 0.9, 81.0, 717.0, 0.0),
        "lemon": (15.0, 9.3, 2.5, 2.8, 1.1, 0.3, 29.0, 20.0),
        "ginger": (5.0, 18.0, 1.7, 2.0, 1.8, 0.8, 80.0, 15.0),
    }

    ing_list: list[dict[str, Any]] = []
    tot_c = tot_s = tot_f = tot_p = tot_fat = tot_k = tot_gl = 0.0

    for tok in tokens:
        if tok in BUILTIN_NUTRITION:
            g, c100, s100, f100, p100, fat100, k100, gi = BUILTIN_NUTRITION[tok]
            ing_list.append({"name": tok.title(), "grams": g})
            tot_c += c100 * g / 100.0
            tot_s += s100 * g / 100.0
            tot_f += f100 * g / 100.0
            tot_p += p100 * g / 100.0
            tot_fat += fat100 * g / 100.0
            tot_k += k100 * g / 100.0
            net_c = max(0.0, (c100 - f100) * g / 100.0)
            tot_gl += (gi * net_c) / 100.0
            continue

        # Word-level match against FoodItem catalog
        matched_food = None
        tok_words = set(re.findall(r"[a-z]+", tok))
        for f in all_foods:
            f_words = set(re.findall(r"[a-z]+", f.name.lower()))
            if tok == f.name.lower() or (tok_words and tok_words.issubset(f_words)):
                matched_food = f
                break
        if matched_food:
            g = 100.0
            ing_list.append({"name": matched_food.name, "grams": g})
            sub = compute_recipe_nutrition([(g, matched_food)])
            tot_c += sub.carbs_g
            tot_s += sub.sugar_g
            tot_f += sub.fibre_g
            tot_p += sub.protein_g
            tot_fat += sub.fat_g
            tot_k += sub.kcal
            tot_gl += sub.estimated_gl
        else:
            # Conservative home estimate for an unlisted spice/produce item
            g = 50.0
            ing_list.append({"name": tok.title(), "grams": g})
            tot_c += 4.0
            tot_s += 1.5
            tot_f += 1.5
            tot_p += 1.5
            tot_fat += 0.5
            tot_k += 28.0
            tot_gl += 1.5

    carbs_g = round(tot_c, 1)
    sugar_g = round(tot_s, 1)
    fibre_g = round(tot_f, 1)
    protein_g = round(tot_p, 1)
    fat_g = round(tot_fat, 1)
    kcal = round(tot_k)
    estimated_gl = round(tot_gl, 1)
    gl_band = "Low" if estimated_gl <= 10 else ("Medium" if estimated_gl <= 19 else "High")

    latest_g = db.scalar(
        select(GlucoseReading)
        .where(GlucoseReading.patient_id == patient.id)
        .order_by(GlucoseReading.recorded_at.desc())
        .limit(1)
    )
    latest_val = latest_g.glucose_mg_dl if latest_g else None

    if gl_band == "Low" and sugar_g <= 8.0:
        verdict = "Suitable — gentle sugar & glycaemic load for your current readings."
    elif gl_band == "Medium":
        verdict = "Suitable in a measured portion; pair with protein or a 15-min walk after eating."
    else:
        verdict = "Higher carb/sugar load — consider a smaller portion or pairing with extra protein/vegetables."

    if latest_val is not None and latest_val > 180:
        verdict += f" (Note: your latest reading is {round(latest_val)} mg/dL, so keep sweet/starchy portions small.)"

    used_names = ", ".join(item["name"] for item in ing_list) or payload.ingredients_text
    steps = [
        f"Prep only your listed ingredients: {used_names}.",
        "Cook the savoury protein/vegetables gently with minimal oil (1 tsp) and season as listed; serve any fresh fruit/salad side in a small measured portion.",
    ]

    settings = get_settings()
    if _is_gemini_key_usable(settings.gemini_api_key):
        prompt = (
            f"Create 3 short diabetes-friendly {payload.meal_type} cooking steps using STRICTLY ONLY these ingredients: "
            + ", ".join(f"{item['grams']:.0f}g {item['name']}" for item in ing_list)
            + " (plus water, pinch of salt, or 1 tsp oil if cooking). "
            "NEVER add wheat, atta, oats, besan, bread, rice, sugar, or any ingredient not in that list. "
            "Return 3 plain sentences separated by newlines WITHOUT step numbers (no '1.', '2.')."
        )
        ok, g_steps, _ = synthesize_plain_text(prompt, api_key=settings.gemini_api_key or "", model=settings.gemini_model)
        if ok and g_steps:
            parsed_steps = [re.sub(r"^\d+[\.\)]\s*", "", s.strip()) for s in g_steps.splitlines() if s.strip()]
            if parsed_steps:
                steps = parsed_steps[:4]

    return {
        "recipe_title": f"Custom {payload.meal_type.title()} from Your Kitchen",
        "matched_ingredients": ing_list,
        "nutrition": {
            "carbs_g": carbs_g,
            "sugar_g": sugar_g,
            "fibre_g": fibre_g,
            "protein_g": protein_g,
            "fat_g": fat_g,
            "kcal": kcal,
            "calories_kcal": kcal,
            "estimated_gl": estimated_gl,
            "gl_band": gl_band,
        },
        "suitability_verdict": verdict,
        "steps": steps,
    }
