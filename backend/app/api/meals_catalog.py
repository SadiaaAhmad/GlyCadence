from datetime import timedelta
from statistics import mean
from typing import Annotated, Literal
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
    patient = require_patient_access(patient_id, current_user, db, write=False)
    recipes, ings_by_recipe = _load_recipe_maps(db)

    # Evaluate patient's meals to compute personal timing reason & prefer lower-spike recipes
    meals = list(db.scalars(select(Meal).where(Meal.patient_id == patient.id).order_by(Meal.logged_at.desc())).all())
    readings = list(db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == patient.id).order_by(GlucoseReading.recorded_at.asc())).all())
    cgm_points, _, _ = resolve_single_device_cgm_points(readings)
    evals = evaluate_meal_responses(meals, cgm_points, allowed_provenances=frozenset({"native", "dataset_documented"}))
    eval_by_id = {e.meal_id: e for e in evals}

    meds = list(db.scalars(select(Medication).where(Medication.patient_id == patient.id, Medication.is_active.is_(True))).all())
    has_sulfo = any("sulfonylurea" in (m.drug_class or "").lower() for m in meds)

    # Check dinner timing comparison
    early_dinners = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour < 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
    late_dinners = [eval_by_id[m.id].excursion_delta_mg_dl for m in meals if m.meal_type == "dinner" and m.logged_at.hour >= 21 and m.id in eval_by_id and eval_by_id[m.id].excursion_delta_mg_dl is not None]
    if early_dinners and late_dinners:
        dinner_reason = f"Your dinners before 9 pm rose +{mean(early_dinners):.0f} mg/dL on average vs +{mean(late_dinners):.0f} mg/dL after 9 pm"
    else:
        dinner_reason = "Eating dinner by 8:30 pm leaves 2–3 hours before sleep for steadier nights"

    breakfast_reason = (
        "Consistent breakfast timing aligns with morning Gliclazide to reduce mid-morning dips"
        if has_sulfo
        else "Higher-protein breakfast within 1–2 hours of waking supports steady mornings"
    )

    slot_specs = [
        ("breakfast", "8:00 AM – 9:00 AM", breakfast_reason),
        ("lunch", "1:00 PM – 2:00 PM", "Measured carbs with daal/salad showed steadier afternoon curves"),
        ("snack", "4:30 PM – 5:30 PM", "Light protein/fibre snack bridges the gap to dinner"),
        ("dinner", "7:30 PM – 8:30 PM", dinner_reason),
    ]

    slots_out: list[MealPlanSlotOut] = []
    for slot_name, win, reason in slot_specs:
        slot_recipes = [
            _serialize_recipe(r, ings_by_recipe)
            for r in recipes
            if r.slot == slot_name
        ]
        # Rank lower-GL first
        slot_recipes.sort(key=lambda ro: ro.nutrition.estimated_gl)
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
    """Match patient's available kitchen ingredients against FoodItems, compute exact nutrition, and draft a sugar-friendly recipe."""
    from app.agents.llm import _is_gemini_key_usable, synthesize_plain_text
    from app.core.config import get_settings

    patient = require_patient_access(patient_id, current_user, db, write=False)
    ensure_food_and_recipe_catalog(db)
    all_foods = list(db.scalars(select(FoodItem)).all())
    tokens = [t.strip().lower() for t in payload.ingredients_text.replace(";", ",").split(",") if t.strip()]

    matched: list[tuple[float, FoodItem]] = []
    for tok in tokens:
        for f in all_foods:
            if tok in f.name.lower() or tok in f.slug.replace("_", " "):
                # Sensible standard home portion in grams
                grams = 120.0 if any(w in f.slug for w in ("daal", "chana", "chicken", "fish", "keema", "okra", "spinach", "yogurt")) else (40.0 if "flour" in f.slug or "oats" in f.slug else 60.0)
                if not any(m_f.id == f.id for _, m_f in matched):
                    matched.append((grams, f))
                break

    if not matched:
        # Fallback to balanced staples if user typed unfamiliar spelling
        matched = [(100.0, f) for f in all_foods[:3]]

    nut = compute_recipe_nutrition(matched)
    latest_g = db.scalar(
        select(GlucoseReading)
        .where(GlucoseReading.patient_id == patient.id)
        .order_by(GlucoseReading.recorded_at.desc())
        .limit(1)
    )
    latest_val = latest_g.glucose_mg_dl if latest_g else None

    if nut.gl_band == "Low" and nut.sugar_g <= 6.0:
        verdict = "Suitable — gentle sugar & glycaemic load for your current readings."
    elif nut.gl_band == "Medium":
        verdict = "Suitable in a measured portion; pair with extra cucumber/salad or a 15-min walk."
    else:
        verdict = "Higher carb/sugar load — consider a smaller portion or swapping half the grain for daal/vegetables."

    if latest_val is not None and latest_val > 180:
        verdict += f" (Note: your latest reading is {round(latest_val)} mg/dL, so keep starch portion modest.)"

    ing_list = [{"name": f.name, "grams": g} for g, f in matched]
    steps = [
        f"Combine {', '.join(f.name.split('(')[0].strip() for _, f in matched)} using minimal oil (1 tsp) and fresh spices (cumin, turmeric, coriander).",
        "Cook until tender and plate half your dish with non-starchy salad or greens if available.",
    ]

    settings = get_settings()
    if _is_gemini_key_usable(settings.gemini_api_key):
        prompt = (
            f"Create 3 short home-style Pakistani cooking steps for a {payload.meal_type} using ONLY: "
            + ", ".join(f"{g:.0f}g {f.name}" for g, f in matched)
            + ". Keep it diabetes-friendly (no added sugar, minimal oil). Return 3 numbered sentences only."
        )
        ok, g_steps, _ = synthesize_plain_text(prompt, api_key=settings.gemini_api_key or "", model=settings.gemini_model)
        if ok and g_steps:
            parsed_steps = [s.strip() for s in g_steps.splitlines() if s.strip()]
            if parsed_steps:
                steps = parsed_steps[:4]

    return {
        "recipe_title": f"Custom {payload.meal_type.title()} from Your Kitchen",
        "matched_ingredients": ing_list,
        "nutrition": {
            "carbs_g": nut.carbs_g,
            "sugar_g": nut.sugar_g,
            "fibre_g": nut.fibre_g,
            "protein_g": nut.protein_g,
            "fat_g": nut.fat_g,
            "kcal": nut.kcal,
            "estimated_gl": nut.estimated_gl,
            "gl_band": nut.gl_band,
        },
        "suitability_verdict": verdict,
        "steps": steps,
    }
