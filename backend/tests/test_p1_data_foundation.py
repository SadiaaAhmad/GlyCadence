from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.analytics import evaluate_meal_responses, resolve_single_device_cgm_points
from app.core.database import get_engine
from app.main import app
from app.models import FoodItem, GlucoseReading, Meal, Recipe, RecipeIngredient
from app.services.food_catalog import compute_recipe_nutrition, ensure_food_and_recipe_catalog
from app.services.synthetic_seed import ensure_v2_demo_environment


def test_p1_tables_and_30_recipes_nutrition_sum() -> None:
    engine = get_engine()
    assert engine is not None
    tables = set(inspect(engine).get_table_names())
    expected_new = {
        "chat_sessions",
        "chat_messages",
        "patient_memory",
        "food_items",
        "recipes",
        "recipe_ingredients",
        "meal_food_links",
        "medication_stock",
        "patient_preferences",
    }
    assert expected_new.issubset(tables)

    with Session(bind=engine) as db:
        recipes = ensure_food_and_recipe_catalog(db)
        assert len(recipes) >= 30

        foods = {f.id: f for f in db.scalars(select(FoodItem)).all()}
        for rec in recipes.values():
            ings = list(db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id == rec.id)).all())
            assert len(ings) >= 2
            nut = compute_recipe_nutrition([(i.grams, foods[i.food_item_id]) for i in ings])
            # Re-verify arithmetic equals exact sum of ingredients
            expected_carbs = round(sum((i.grams / 100.0) * foods[i.food_item_id].carbs_g_per_100g for i in ings), 1)
            expected_sugar = round(sum((i.grams / 100.0) * foods[i.food_item_id].sugar_g_per_100g for i in ings), 1)
            assert nut.carbs_g == expected_carbs
            assert nut.sugar_g == expected_sugar
            assert rec.image_url.startswith("/images/meals/") or rec.image_url.startswith("https://")


def test_p1_synthetic_patients_have_aligned_valid_meals_and_readings_endpoints() -> None:
    engine = get_engine()
    assert engine is not None
    with Session(bind=engine) as db:
        p1, p2 = ensure_v2_demo_environment(db, force_regenerate=True)
        assert p1.external_id == "SYNTH-DEMO-001"
        assert p2.external_id == "SYNTH-DEMO-002"

        meals = list(db.scalars(select(Meal).where(Meal.patient_id == p1.id)).all())
        readings = list(db.scalars(select(GlucoseReading).where(GlucoseReading.patient_id == p1.id).order_by(GlucoseReading.recorded_at.asc())).all())
        assert len(meals) >= 24
        assert len(readings) >= 3500

        cgm_pts, _, _ = resolve_single_device_cgm_points(readings)
        evals = evaluate_meal_responses(meals, cgm_pts)
        valid_count = sum(1 for e in evals if e.iauc_valid)
        assert valid_count / len(meals) >= 0.80

    with TestClient(app) as client:
        email = f"p1_test_{p1.id.hex[:8]}@example.com"
        reg = client.post("/api/v1/auth/register", json={"email": email, "password": "TestPassword123!"})
        assert reg.status_code in (201, 409)
        tok = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPassword123!"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        r_read = client.get(f"/api/v1/patients/{p1.id}/glucose/readings?days=7", headers=headers)
        assert r_read.status_code == 200
        assert len(r_read.json()["readings"]) > 0
        assert len(r_read.json()["markers"]) > 0

        r_agp = client.get(f"/api/v1/patients/{p1.id}/glucose/daily-pattern?days=14", headers=headers)
        assert r_agp.status_code == 200
        assert len(r_agp.json()["hours"]) == 24

        r_plan = client.get(f"/api/v1/patients/{p1.id}/meals/plan", headers=headers)
        assert r_plan.status_code == 200
        assert len(r_plan.json()["slots"]) == 4

        first_meal_id = meals[0].id
        r_md = client.get(f"/api/v1/patients/{p1.id}/meals/{first_meal_id}", headers=headers)
        assert r_md.status_code == 200
        md_json = r_md.json()
        assert md_json["recipe"]["nutrition"]["sugar_g"] >= 0
        assert md_json["personal_history"]["times_observed"] >= 1
        assert len(md_json["personal_history"]["curve_points"]) > 0
