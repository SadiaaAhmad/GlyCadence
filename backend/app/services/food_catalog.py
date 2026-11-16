"""Curated USDA FoodData Central + Pakistani food items and 30 authentic desi recipes.

All per-recipe nutrients (carbs, sugar, fibre, protein, fat, kcal, glycaemic load)
are computed deterministically from ``sum(grams / 100 * food_item_nutrient)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.v2 import FoodItem, Recipe, RecipeIngredient


_LOCAL_IMAGE_MAP = {
    "Masala_Omelette.jpg": "/images/meals/omelette_roti.jpg",
    "Aloo_paratha.jpg": "/images/meals/omelette_roti.jpg",
    "Roti_%2C_Chany_ki_Dal_and_Salad_with_cut_Onion_and_Tomatoes.jpg": "/images/meals/daal_roti.jpg",
    "Indian_Fruit_Chaat.jpg": "/images/meals/chana_chaat.jpg",
    "Chana_masala.jpg": "/images/meals/daal_roti.jpg",
    "Chana_Chaat.jpg": "/images/meals/chana_chaat.jpg",
    "Raita_with_cucumber_and_mint.jpg": "/images/meals/chana_chaat.jpg",
    "Chicken_Tikka.jpg": "/images/meals/chicken_tikka.jpg",
    "Palak_Paneer_%26_Methi_Roti.jpg": "/images/meals/daal_roti.jpg",
    "Bhindi_Masala.jpg": "/images/meals/daal_roti.jpg",
    "Tandoori_roti_and_chole.jpg": "/images/meals/daal_roti.jpg",
    "Pakistani_biryani.jpg": "/images/meals/biryani.jpg",
    "Chicken_Karahi_in_Pakistan.jpg": "/images/meals/karahi_roti.jpg",
    "Beef_Korma.JPG": "/images/meals/karahi_roti.jpg",
    "Beef_Nihari.JPG": "/images/meals/karahi_roti.jpg",
}


def _wm(filename: str) -> str:
    return _LOCAL_IMAGE_MAP.get(filename, "/images/meals/daal_roti.jpg")


# Per-100g nutrient reference values from USDA FoodData Central / curated Pakistani composition
FOOD_ITEM_DEFS: list[dict] = [
    {"slug": "whole_wheat_flour", "name": "Whole-wheat atta (chapati flour)", "name_ur": "چکی کا آٹا", "source": "pk_curated", "source_reference": "USDA FDC Wheat flour, whole-grain (#168893)", "carbs_g_per_100g": 72.0, "sugar_g_per_100g": 0.4, "fibre_g_per_100g": 10.7, "protein_g_per_100g": 13.2, "fat_g_per_100g": 2.5, "kcal_per_100g": 340.0, "gi": 52.0},
    {"slug": "besan_chickpea_flour", "name": "Besan (gram / chickpea flour)", "name_ur": "بیسن", "source": "usda_fdc", "source_reference": "USDA FDC Chickpea flour (#174288)", "carbs_g_per_100g": 57.8, "sugar_g_per_100g": 10.8, "fibre_g_per_100g": 10.8, "protein_g_per_100g": 22.4, "fat_g_per_100g": 6.7, "kcal_per_100g": 387.0, "gi": 35.0},
    {"slug": "rolled_oats", "name": "Rolled oats (dry)", "name_ur": "جئی کا دلیہ", "source": "usda_fdc", "source_reference": "USDA FDC Oats, regular & quick (#173904)", "carbs_g_per_100g": 66.3, "sugar_g_per_100g": 1.0, "fibre_g_per_100g": 10.6, "protein_g_per_100g": 16.9, "fat_g_per_100g": 6.9, "kcal_per_100g": 389.0, "gi": 55.0},
    {"slug": "broken_wheat_dalia", "name": "Cracked wheat (dalia, dry)", "name_ur": "گندم کا دلیہ", "source": "pk_curated", "source_reference": "USDA FDC Bulgur, dry (#170286)", "carbs_g_per_100g": 75.9, "sugar_g_per_100g": 0.4, "fibre_g_per_100g": 12.5, "protein_g_per_100g": 12.3, "fat_g_per_100g": 1.3, "kcal_per_100g": 342.0, "gi": 48.0},
    {"slug": "brown_basmati_cooked", "name": "Brown basmati rice (cooked)", "name_ur": "براؤن چاول", "source": "usda_fdc", "source_reference": "USDA FDC Rice, brown, long-grain, cooked (#169704)", "carbs_g_per_100g": 23.0, "sugar_g_per_100g": 0.4, "fibre_g_per_100g": 1.8, "protein_g_per_100g": 2.6, "fat_g_per_100g": 0.9, "kcal_per_100g": 111.0, "gi": 50.0},
    {"slug": "white_basmati_cooked", "name": "White basmati rice (cooked)", "name_ur": "سفید باسمتی چاول", "source": "usda_fdc", "source_reference": "USDA FDC Rice, white, long-grain, cooked (#168878)", "carbs_g_per_100g": 28.2, "sugar_g_per_100g": 0.1, "fibre_g_per_100g": 0.4, "protein_g_per_100g": 2.7, "fat_g_per_100g": 0.3, "kcal_per_100g": 130.0, "gi": 68.0},
    {"slug": "chana_daal_cooked", "name": "Chana daal (split Bengal gram, cooked)", "name_ur": "چنے کی دال", "source": "pk_curated", "source_reference": "USDA FDC Chickpeas/Split gram cooked equiv (#173757)", "carbs_g_per_100g": 21.0, "sugar_g_per_100g": 2.4, "fibre_g_per_100g": 6.8, "protein_g_per_100g": 8.9, "fat_g_per_100g": 1.8, "kcal_per_100g": 136.0, "gi": 28.0},
    {"slug": "moong_daal_cooked", "name": "Moong daal (yellow split mung, cooked)", "name_ur": "مونگ کی دال", "source": "usda_fdc", "source_reference": "USDA FDC Mung beans, boiled (#174256)", "carbs_g_per_100g": 19.2, "sugar_g_per_100g": 2.0, "fibre_g_per_100g": 7.6, "protein_g_per_100g": 7.0, "fat_g_per_100g": 0.4, "kcal_per_100g": 105.0, "gi": 31.0},
    {"slug": "masoor_daal_cooked", "name": "Masoor daal (red lentils, cooked)", "name_ur": "مسور کی دال", "source": "usda_fdc", "source_reference": "USDA FDC Lentils, boiled (#172421)", "carbs_g_per_100g": 20.1, "sugar_g_per_100g": 1.8, "fibre_g_per_100g": 7.9, "protein_g_per_100g": 9.0, "fat_g_per_100g": 0.4, "kcal_per_100g": 116.0, "gi": 29.0},
    {"slug": "kabuli_chana_cooked", "name": "Chickpeas / safed chana (cooked)", "name_ur": "سفید چنے", "source": "usda_fdc", "source_reference": "USDA FDC Chickpeas, boiled (#173757)", "carbs_g_per_100g": 27.4, "sugar_g_per_100g": 4.8, "fibre_g_per_100g": 7.6, "protein_g_per_100g": 8.9, "fat_g_per_100g": 2.6, "kcal_per_100g": 164.0, "gi": 28.0},
    {"slug": "kala_chana_cooked", "name": "Black chickpeas / kala chana (cooked)", "name_ur": "کالے چنے", "source": "pk_curated", "source_reference": "USDA FDC Chickpeas cooked (#173757)", "carbs_g_per_100g": 24.5, "sugar_g_per_100g": 3.5, "fibre_g_per_100g": 8.4, "protein_g_per_100g": 9.2, "fat_g_per_100g": 2.4, "kcal_per_100g": 152.0, "gi": 25.0},
    {"slug": "rajma_cooked", "name": "Red kidney beans / rajma (cooked)", "name_ur": "لوبیا / راجما", "source": "usda_fdc", "source_reference": "USDA FDC Beans, kidney, red, boiled (#173740)", "carbs_g_per_100g": 22.8, "sugar_g_per_100g": 0.3, "fibre_g_per_100g": 6.4, "protein_g_per_100g": 8.7, "fat_g_per_100g": 0.5, "kcal_per_100g": 127.0, "gi": 24.0},
    {"slug": "egg_whole", "name": "Chicken egg (whole)", "name_ur": "انڈا", "source": "usda_fdc", "source_reference": "USDA FDC Egg, whole, raw (#171287)", "carbs_g_per_100g": 0.7, "sugar_g_per_100g": 0.4, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 12.6, "fat_g_per_100g": 9.5, "kcal_per_100g": 143.0, "gi": 0.0},
    {"slug": "chicken_breast", "name": "Chicken breast (boneless, skinless)", "name_ur": "مرغی کا سینہ", "source": "usda_fdc", "source_reference": "USDA FDC Chicken, breast (#171077)", "carbs_g_per_100g": 0.0, "sugar_g_per_100g": 0.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 22.5, "fat_g_per_100g": 2.6, "kcal_per_100g": 120.0, "gi": 0.0},
    {"slug": "lean_beef_keema", "name": "Lean beef mince (keema)", "name_ur": "قیمہ", "source": "usda_fdc", "source_reference": "USDA FDC Beef, ground, 90% lean (#174032)", "carbs_g_per_100g": 0.0, "sugar_g_per_100g": 0.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 20.0, "fat_g_per_100g": 10.0, "kcal_per_100g": 176.0, "gi": 0.0},
    {"slug": "rohu_fish", "name": "Rohu / white fish fillet", "name_ur": "مچھلی", "source": "usda_fdc", "source_reference": "USDA FDC Fish, carp/whitefish (#171950)", "carbs_g_per_100g": 0.0, "sugar_g_per_100g": 0.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 18.0, "fat_g_per_100g": 2.5, "kcal_per_100g": 97.0, "gi": 0.0},
    {"slug": "paneer", "name": "Homemade paneer (cottage cheese)", "name_ur": "پنیر", "source": "pk_curated", "source_reference": "USDA FDC Cheese, cottage/paneer equiv (#170894)", "carbs_g_per_100g": 3.4, "sugar_g_per_100g": 2.6, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 18.3, "fat_g_per_100g": 20.8, "kcal_per_100g": 265.0, "gi": 15.0},
    {"slug": "plain_yogurt", "name": "Plain dahi (whole-milk yogurt, unsweetened)", "name_ur": "دہی", "source": "usda_fdc", "source_reference": "USDA FDC Yogurt, plain, whole milk (#171284)", "carbs_g_per_100g": 4.7, "sugar_g_per_100g": 4.7, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 3.5, "fat_g_per_100g": 3.3, "kcal_per_100g": 61.0, "gi": 28.0},
    {"slug": "milk_lowfat", "name": "Low-fat milk (1%)", "name_ur": "دودھ", "source": "usda_fdc", "source_reference": "USDA FDC Milk, lowfat, 1% (#171266)", "carbs_g_per_100g": 5.0, "sugar_g_per_100g": 5.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 3.4, "fat_g_per_100g": 1.0, "kcal_per_100g": 42.0, "gi": 31.0},
    {"slug": "spinach_palak", "name": "Fresh spinach (palak)", "name_ur": "پالک", "source": "usda_fdc", "source_reference": "USDA FDC Spinach, raw (#168462)", "carbs_g_per_100g": 3.6, "sugar_g_per_100g": 0.4, "fibre_g_per_100g": 2.2, "protein_g_per_100g": 2.9, "fat_g_per_100g": 0.4, "kcal_per_100g": 23.0, "gi": 15.0},
    {"slug": "okra_bhindi", "name": "Okra (bhindi)", "name_ur": "بھنڈی", "source": "usda_fdc", "source_reference": "USDA FDC Okra, raw (#169260)", "carbs_g_per_100g": 7.5, "sugar_g_per_100g": 1.5, "fibre_g_per_100g": 3.2, "protein_g_per_100g": 1.9, "fat_g_per_100g": 0.2, "kcal_per_100g": 33.0, "gi": 20.0},
    {"slug": "tomato", "name": "Fresh tomatoes", "name_ur": "ٹماٹر", "source": "usda_fdc", "source_reference": "USDA FDC Tomatoes, red, ripe (#170457)", "carbs_g_per_100g": 3.9, "sugar_g_per_100g": 2.6, "fibre_g_per_100g": 1.2, "protein_g_per_100g": 0.9, "fat_g_per_100g": 0.2, "kcal_per_100g": 18.0, "gi": 15.0},
    {"slug": "onion", "name": "Red onion", "name_ur": "پیاز", "source": "usda_fdc", "source_reference": "USDA FDC Onions, raw (#170000)", "carbs_g_per_100g": 9.3, "sugar_g_per_100g": 4.2, "fibre_g_per_100g": 1.7, "protein_g_per_100g": 1.1, "fat_g_per_100g": 0.1, "kcal_per_100g": 40.0, "gi": 15.0},
    {"slug": "cucumber", "name": "Cucumber", "name_ur": "کھیرا", "source": "usda_fdc", "source_reference": "USDA FDC Cucumber, with peel (#168409)", "carbs_g_per_100g": 3.6, "sugar_g_per_100g": 1.7, "fibre_g_per_100g": 0.5, "protein_g_per_100g": 0.7, "fat_g_per_100g": 0.1, "kcal_per_100g": 15.0, "gi": 15.0},
    {"slug": "green_peas", "name": "Green peas (matar)", "name_ur": "مٹر", "source": "usda_fdc", "source_reference": "USDA FDC Peas, green, raw (#170419)", "carbs_g_per_100g": 14.5, "sugar_g_per_100g": 5.7, "fibre_g_per_100g": 5.7, "protein_g_per_100g": 5.4, "fat_g_per_100g": 0.4, "kcal_per_100g": 81.0, "gi": 48.0},
    {"slug": "potato", "name": "Potato (boiled/cooked)", "name_ur": "آلو", "source": "usda_fdc", "source_reference": "USDA FDC Potatoes, boiled (#170032)", "carbs_g_per_100g": 20.1, "sugar_g_per_100g": 0.9, "fibre_g_per_100g": 1.8, "protein_g_per_100g": 1.9, "fat_g_per_100g": 0.1, "kcal_per_100g": 87.0, "gi": 78.0},
    {"slug": "bitter_gourd_karela", "name": "Bitter gourd (karela)", "name_ur": "کریلا", "source": "usda_fdc", "source_reference": "USDA FDC Balsam-pear, pods (#169210)", "carbs_g_per_100g": 3.7, "sugar_g_per_100g": 1.0, "fibre_g_per_100g": 2.8, "protein_g_per_100g": 1.0, "fat_g_per_100g": 0.2, "kcal_per_100g": 17.0, "gi": 15.0},
    {"slug": "apple", "name": "Apple (with skin)", "name_ur": "سیب", "source": "usda_fdc", "source_reference": "USDA FDC Apples, raw (#171688)", "carbs_g_per_100g": 13.8, "sugar_g_per_100g": 10.4, "fibre_g_per_100g": 2.4, "protein_g_per_100g": 0.3, "fat_g_per_100g": 0.2, "kcal_per_100g": 52.0, "gi": 36.0},
    {"slug": "guava", "name": "Guava (amrood)", "name_ur": "امرود", "source": "usda_fdc", "source_reference": "USDA FDC Guavas, common (#173044)", "carbs_g_per_100g": 14.3, "sugar_g_per_100g": 8.9, "fibre_g_per_100g": 5.4, "protein_g_per_100g": 2.6, "fat_g_per_100g": 1.0, "kcal_per_100g": 68.0, "gi": 24.0},
    {"slug": "dates_medjool", "name": "Dates (khajoor)", "name_ur": "کھجور", "source": "usda_fdc", "source_reference": "USDA FDC Dates, medjool (#168191)", "carbs_g_per_100g": 75.0, "sugar_g_per_100g": 66.5, "fibre_g_per_100g": 6.7, "protein_g_per_100g": 1.8, "fat_g_per_100g": 0.2, "kcal_per_100g": 277.0, "gi": 42.0},
    {"slug": "almonds", "name": "Almonds (badaam)", "name_ur": "بادام", "source": "usda_fdc", "source_reference": "USDA FDC Nuts, almonds (#170567)", "carbs_g_per_100g": 21.6, "sugar_g_per_100g": 4.4, "fibre_g_per_100g": 12.5, "protein_g_per_100g": 21.2, "fat_g_per_100g": 49.9, "kcal_per_100g": 579.0, "gi": 15.0},
    {"slug": "olive_oil", "name": "Cooking oil / olive oil", "name_ur": "کھانے کا تیل", "source": "usda_fdc", "source_reference": "USDA FDC Oil, olive (#171413)", "carbs_g_per_100g": 0.0, "sugar_g_per_100g": 0.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 0.0, "fat_g_per_100g": 100.0, "kcal_per_100g": 884.0, "gi": 0.0},
    {"slug": "ghee", "name": "Desi ghee (clarified butter)", "name_ur": "دیسی گھی", "source": "usda_fdc", "source_reference": "USDA FDC Butter oil (#173430)", "carbs_g_per_100g": 0.0, "sugar_g_per_100g": 0.0, "fibre_g_per_100g": 0.0, "protein_g_per_100g": 0.0, "fat_g_per_100g": 99.5, "kcal_per_100g": 876.0, "gi": 0.0},
]


# 30 curated Pakistani / South Asian recipes (10 breakfast, 10 lunch/dinner, 10 snacks/suhoor/iftar)
RECIPE_DEFS: list[dict] = [
    # --- BREAKFAST (8 + 2 Suhoor) ---
    {
        "slug": "masala-omelette-1-roti",
        "name": "Masala omelette with 1 small whole-wheat roti",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 15,
        "image_url": _wm("Masala_Omelette.jpg"),
        "tags": ["high_protein", "desi", "budget", "quick", "low_gl"],
        "guidance_note": "Eggs and vegetables provide protein and fibre with minimal added sugar; pairing with 1 modest whole-wheat roti typically produces a gentler morning curve than 2 parathas.",
        "steps": [
            "Whisk 2 eggs with finely chopped onion, tomato, green chilli, coriander, and a pinch of turmeric.",
            "Cook in 1 tsp oil on a flat tawa for 3–4 minutes until set.",
            "Serve warm with 1 thin whole-wheat chapati (approx. 45g dough).",
        ],
        "ingredients": [("egg_whole", 100), ("onion", 30), ("tomato", 40), ("whole_wheat_flour", 35), ("olive_oil", 5)],
    },
    {
        "slug": "whole-wheat-paratha-egg",
        "name": "Whole-wheat dry paratha with boiled egg & plain dahi",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 15,
        "image_url": _wm("Aloo_paratha.jpg"),
        "tags": ["desi", "vegetarian_option", "budget"],
        "guidance_note": "Adding a boiled egg and unsweetened yogurt slows stomach emptying compared to eating paratha alone with sweet chai.",
        "steps": [
            "Roll 1 medium whole-wheat atta ball (50g) and brush lightly with 1 tsp ghee while roasting.",
            "Boil 1 large egg (8 minutes).",
            "Serve together with half a katori of plain unsweetened dahi.",
        ],
        "ingredients": [("whole_wheat_flour", 50), ("egg_whole", 55), ("plain_yogurt", 80), ("ghee", 5)],
    },
    {
        "slug": "besan-chilla-mint-dahi",
        "name": "Savory besan chilla (2 crepes) with mint dahi",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 15,
        "image_url": _wm("Roti_%2C_Chany_ki_Dal_and_Salad_with_cut_Onion_and_Tomatoes.jpg"),
        "tags": ["vegetarian", "high_fibre", "low_gl", "desi", "budget"],
        "guidance_note": "Chickpea flour (besan) is higher in protein and soluble fibre than refined wheat, giving a low glycaemic load breakfast.",
        "steps": [
            "Mix 55g besan with water, chopped onion, tomato, cumin, and coriander to form a pourable batter.",
            "Pour onto a lightly oiled non-stick pan and cook 2 thin chillas.",
            "Serve with plain mint-seasoned yogurt.",
        ],
        "ingredients": [("besan_chickpea_flour", 55), ("onion", 30), ("tomato", 35), ("plain_yogurt", 80), ("olive_oil", 5)],
    },
    {
        "slug": "oats-almond-cinnamon-porridge",
        "name": "Unsweetened rolled oats with milk, almonds & apple",
        "slot": "breakfast",
        "cost_tier": "medium",
        "prep_min": 10,
        "image_url": _wm("Indian_Fruit_Chaat.jpg"),
        "tags": ["vegetarian", "high_fibre", "quick"],
        "guidance_note": "Beta-glucan fibre in whole rolled oats helps blunt morning glucose swings; skip honey or jaggery to keep free sugar low.",
        "steps": [
            "Simmer 40g rolled oats in 150ml low-fat milk and water for 5 minutes.",
            "Top with 10g chopped almonds, cinnamon powder, and 50g diced fresh apple.",
        ],
        "ingredients": [("rolled_oats", 40), ("milk_lowfat", 150), ("almonds", 10), ("apple", 50)],
    },
    {
        "slug": "wheat-dalia-vegetable-khichdi",
        "name": "Cracked wheat (dalia) savory breakfast porridge",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 20,
        "image_url": _wm("Chana_masala.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget"],
        "guidance_note": "Cracked whole wheat combined with moong dal keeps cereal intake intact-grain with extra fibre.",
        "steps": [
            "Lightly toast 40g broken wheat dalia in 1 tsp oil with cumin seeds.",
            "Add chopped tomato, onion, and 40g cooked yellow moong dal with water; simmer until tender.",
        ],
        "ingredients": [("broken_wheat_dalia", 40), ("moong_daal_cooked", 40), ("tomato", 40), ("onion", 25), ("olive_oil", 5)],
    },
    {
        "slug": "kala-chana-breakfast-bowl",
        "name": "Spiced kala chana bowl with cucumber & boiled egg",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 12,
        "image_url": _wm("Chana_Chaat.jpg"),
        "tags": ["high_fibre", "low_gl", "desi", "budget", "quick"],
        "guidance_note": "Black chickpeas (kala chana) have one of the lowest glycaemic indices among staples and keep fullness steady until lunch.",
        "steps": [
            "Toss 120g boiled kala chana with chopped onion, tomato, cucumber, lemon juice, and chaat masala.",
            "Serve alongside 1 sliced boiled egg.",
        ],
        "ingredients": [("kala_chana_cooked", 120), ("cucumber", 50), ("tomato", 40), ("onion", 25), ("egg_whole", 55)],
    },
    {
        "slug": "shakshuka-egg-roti",
        "name": "Spiced tomato-pepper egg skillet with 1 small chapati",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 18,
        "image_url": _wm("Masala_Omelette.jpg"),
        "tags": ["high_protein", "low_gl", "quick"],
        "guidance_note": "Tomato-simmered eggs deliver high protein and negligible sugar.",
        "steps": [
            "Sauté chopped onion and tomato with cumin and paprika in 1 tsp olive oil until thick.",
            "Make 2 wells, crack 2 eggs, cover and cook 4 minutes.",
            "Serve with 1 small whole-wheat roti.",
        ],
        "ingredients": [("egg_whole", 100), ("tomato", 110), ("onion", 35), ("whole_wheat_flour", 35), ("olive_oil", 5)],
    },
    {
        "slug": "dahi-chia-guava-bowl",
        "name": "Plain dahi bowl with fresh guava & almonds",
        "slot": "breakfast",
        "cost_tier": "low",
        "prep_min": 5,
        "image_url": _wm("Raita_with_cucumber_and_mint.jpg"),
        "tags": ["vegetarian", "low_gl", "quick", "budget"],
        "guidance_note": "Guava is rich in soluble fibre and lower in free sugar than mangoes or grapes.",
        "steps": [
            "Whisk 150g plain unsweetened yogurt until smooth.",
            "Top with 90g sliced fresh guava, 12g almonds, and a pinch of roasted cumin.",
        ],
        "ingredients": [("plain_yogurt", 150), ("guava", 90), ("almonds", 12)],
    },

    # --- LUNCH (8) ---
    {
        "slug": "chana-daal-brown-rice-salad",
        "name": "Chana daal with modest brown rice & kachumber salad",
        "slot": "lunch",
        "cost_tier": "low",
        "prep_min": 25,
        "image_url": _wm("Roti_%2C_Chany_ki_Dal_and_Salad_with_cut_Onion_and_Tomatoes.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget", "low_gl"],
        "guidance_note": "Keeping cooked rice to ~100g (half katori) alongside fibre-rich chana daal and crunchy salad slows carb absorption.",
        "steps": [
            "Prepare homestyle chana daal tempered with garlic, cumin, and 1 tsp oil.",
            "Plate 150g chana daal with 100g cooked brown basmati rice.",
            "Fill half the plate with fresh cucumber-tomato-onion kachumber.",
        ],
        "ingredients": [("chana_daal_cooked", 150), ("brown_basmati_cooked", 100), ("cucumber", 70), ("tomato", 60), ("onion", 25), ("olive_oil", 5)],
    },
    {
        "slug": "chicken-tikka-roti-raita",
        "name": "Grilled chicken tikka with 1 whole-wheat chapati & cucumber raita",
        "slot": "lunch",
        "cost_tier": "medium",
        "prep_min": 25,
        "image_url": _wm("Chicken_Tikka.jpg"),
        "tags": ["high_protein", "low_gl", "desi"],
        "guidance_note": "Lean grilled chicken paired with cucumber raita keeps post-lunch glycaemic load moderate.",
        "steps": [
            "Marinate 140g chicken breast cubes in yogurt, lemon, ginger-garlic, and tikka spices; grill or air-fry.",
            "Serve with 1 whole-wheat roti and a bowl of cucumber-mint raita.",
        ],
        "ingredients": [("chicken_breast", 140), ("plain_yogurt", 90), ("cucumber", 70), ("whole_wheat_flour", 40), ("olive_oil", 5)],
    },
    {
        "slug": "palak-paneer-methi-roti",
        "name": "Palak paneer with 1 whole-wheat chapati",
        "slot": "lunch",
        "cost_tier": "medium",
        "prep_min": 25,
        "image_url": _wm("Palak_Paneer_%26_Methi_Roti.jpg"),
        "tags": ["vegetarian", "high_protein", "low_gl", "desi"],
        "guidance_note": "Spinach adds potassium and fibre while paneer contributes protein and healthy satiety with very little sugar.",
        "steps": [
            "Blanch and blend 160g fresh spinach; simmer with sautéed onion, tomato, garlic, and spices.",
            "Fold in 75g lightly seared paneer cubes and serve with 1 whole-wheat roti.",
        ],
        "ingredients": [("spinach_palak", 160), ("paneer", 75), ("tomato", 50), ("onion", 30), ("whole_wheat_flour", 40), ("olive_oil", 6)],
    },
    {
        "slug": "bhindi-masala-chapati-dahi",
        "name": "Bhindi masala (okra) with 1 chapati & plain dahi",
        "slot": "lunch",
        "cost_tier": "low",
        "prep_min": 22,
        "image_url": _wm("Bhindi_Masala.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget", "low_gl"],
        "guidance_note": "Okra (bhindi) is rich in mucilaginous soluble fibre, well suited for steady midday glucose.",
        "steps": [
            "Stir-fry 160g sliced bhindi with onion, tomato, coriander powder, and turmeric in 1.5 tsp oil.",
            "Serve with 1 whole-wheat chapati and 75g plain yogurt.",
        ],
        "ingredients": [("okra_bhindi", 160), ("onion", 45), ("tomato", 55), ("whole_wheat_flour", 40), ("plain_yogurt", 75), ("olive_oil", 7)],
    },
    {
        "slug": "masoor-daal-brown-rice-bowl",
        "name": "Masoor daal tadka with brown rice & cucumber salad",
        "slot": "lunch",
        "cost_tier": "low",
        "prep_min": 20,
        "image_url": _wm("Tandoori_roti_and_chole.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget"],
        "guidance_note": "Red lentils cook quickly and provide plant protein plus 11g+ fibre per serving.",
        "steps": [
            "Simmer masoor lentils with turmeric until creamy; finish with garlic-cumin tadka.",
            "Serve 150g daal over 100g brown rice with cucumber salad.",
        ],
        "ingredients": [("masoor_daal_cooked", 150), ("brown_basmati_cooked", 100), ("cucumber", 80), ("tomato", 40), ("olive_oil", 5)],
    },
    {
        "slug": "rajma-brown-rice-kachumber",
        "name": "Lahori rajma masala with modest brown rice & salad",
        "slot": "lunch",
        "cost_tier": "low",
        "prep_min": 25,
        "image_url": _wm("Chana_masala.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget", "low_gl"],
        "guidance_note": "Red kidney beans digest slowly, supporting flatter afternoon curves.",
        "steps": [
            "Simmer 150g boiled kidney beans in onion-tomato-ginger masala.",
            "Plate alongside 90g brown basmati rice and cucumber-tomato salad.",
        ],
        "ingredients": [("rajma_cooked", 150), ("brown_basmati_cooked", 90), ("tomato", 60), ("onion", 30), ("cucumber", 60), ("olive_oil", 5)],
    },
    {
        "slug": "chicken-biryani-balanced-portion",
        "name": "Modest chicken biryani (measured cup) with cucumber raita",
        "slot": "lunch",
        "cost_tier": "medium",
        "prep_min": 35,
        "image_url": _wm("Pakistani_biryani.jpg"),
        "tags": ["desi", "high_protein"],
        "guidance_note": "Traditional biryani can spike if eaten as a full plate; measuring 130g cooked rice with extra chicken and raita reduces glycaemic load.",
        "steps": [
            "Combine 130g cooked basmati rice with 120g spiced chicken pieces.",
            "Pair with 100g cucumber-mint raita and fresh salad before eating the rice.",
        ],
        "ingredients": [("white_basmati_cooked", 130), ("chicken_breast", 120), ("plain_yogurt", 100), ("cucumber", 60), ("olive_oil", 7)],
    },
    {
        "slug": "chole-masala-1-roti",
        "name": "Pindi chole (chickpea curry) with 1 tandoori roti",
        "slot": "lunch",
        "cost_tier": "low",
        "prep_min": 25,
        "image_url": _wm("Tandoori_roti_and_chole.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget"],
        "guidance_note": "Keep portion to 1 modest roti rather than fried bhatura or naan.",
        "steps": [
            "Simmer 140g cooked safed chana in spiced tomato-onion gravy.",
            "Serve with 1 dry-roasted whole-wheat roti and sliced onion/cucumber.",
        ],
        "ingredients": [("kabuli_chana_cooked", 140), ("tomato", 60), ("onion", 40), ("whole_wheat_flour", 40), ("cucumber", 50), ("olive_oil", 5)],
    },

    # --- DINNER (8) ---
    {
        "slug": "chicken-karahi-1-chapati",
        "name": "Homestyle chicken karahi with 1 chapati & salad",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 30,
        "image_url": _wm("Chicken_Karahi_in_Pakistan.jpg"),
        "tags": ["high_protein", "desi", "low_gl"],
        "guidance_note": "Eating dinner before 8:30–9:00 pm with 1 modest chapati supports steadier overnight glucose.",
        "steps": [
            "Simmer 140g boneless chicken with tomatoes, ginger, garlic, and black pepper in 1.5 tsp oil.",
            "Serve with 1 small whole-wheat chapati and fresh salad.",
        ],
        "ingredients": [("chicken_breast", 140), ("tomato", 110), ("whole_wheat_flour", 40), ("cucumber", 70), ("olive_oil", 7)],
    },
    {
        "slug": "keema-matar-whole-roti",
        "name": "Lean beef keema matar with 1 whole-wheat roti",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 30,
        "image_url": _wm("Beef_Korma.JPG"),
        "tags": ["high_protein", "desi", "low_gl"],
        "guidance_note": "Skipping potatoes in keema and pairing with peas keeps dinner carb count predictable.",
        "steps": [
            "Brown 120g lean beef mince with ginger-garlic, onion, and tomato.",
            "Add 50g green peas and simmer 10 minutes; serve with 1 chapati.",
        ],
        "ingredients": [("lean_beef_keema", 120), ("green_peas", 50), ("tomato", 60), ("onion", 35), ("whole_wheat_flour", 40), ("olive_oil", 5)],
    },
    {
        "slug": "masala-grilled-fish-salad",
        "name": "Lahori masala grilled fish with roasted veggies",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 20,
        "image_url": _wm("Chicken_Tikka.jpg"),
        "tags": ["high_protein", "low_gl", "quick", "desi"],
        "guidance_note": "Baked or tawa-grilled fish (not batter-fried) keeps dinner low in carbs and fat.",
        "steps": [
            "Rub 160g fish fillet with lemon juice, ajwain, cumin, and garlic.",
            "Pan-sear or bake for 10–12 minutes and serve with cucumber-tomato salad and 70g dahi.",
        ],
        "ingredients": [("rohu_fish", 160), ("cucumber", 80), ("tomato", 70), ("plain_yogurt", 70), ("olive_oil", 6)],
    },
    {
        "slug": "moong-daal-khichdi-light-dinner",
        "name": "Moong daal & brown rice light khichdi with raita",
        "slot": "dinner",
        "cost_tier": "low",
        "prep_min": 25,
        "image_url": _wm("Roti_%2C_Chany_ki_Dal_and_Salad_with_cut_Onion_and_Tomatoes.jpg"),
        "tags": ["vegetarian", "desi", "budget", "high_fibre"],
        "guidance_note": "Gentle on digestion and suitable for sick days or light evening meals when paired with yogurt.",
        "steps": [
            "Combine 120g cooked moong daal with 85g cooked brown rice, turmeric, and cumin.",
            "Serve warm with 90g cucumber raita.",
        ],
        "ingredients": [("moong_daal_cooked", 120), ("brown_basmati_cooked", 85), ("plain_yogurt", 90), ("cucumber", 50), ("olive_oil", 4)],
    },
    {
        "slug": "karela-keema-light-roti",
        "name": "Stuffed/stir-fried karela keema with 1 small chapati",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 30,
        "image_url": _wm("Bhindi_Masala.jpg"),
        "tags": ["desi", "high_protein", "high_fibre", "low_gl"],
        "guidance_note": "Non-starchy bitter gourd adds fibre and volume without raising meal carbohydrate load.",
        "steps": [
            "Sauté 120g sliced karela with onion until tender.",
            "Combine with 100g lean cooked keema and tomato; serve with 1 small chapati.",
        ],
        "ingredients": [("bitter_gourd_karela", 120), ("lean_beef_keema", 100), ("onion", 40), ("tomato", 45), ("whole_wheat_flour", 35), ("olive_oil", 6)],
    },
    {
        "slug": "paneer-tikka-salad-bowl",
        "name": "Tandoori paneer tikka bowl with cucumber & mint raita",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 20,
        "image_url": _wm("Palak_Paneer_%26_Methi_Roti.jpg"),
        "tags": ["vegetarian", "high_protein", "low_gl", "quick"],
        "guidance_note": "A low-carb dinner option for nights when earlier meals already met daily carbohydrate intake.",
        "steps": [
            "Grill 110g paneer cubes marinated in yogurt and spices alongside onion and tomato.",
            "Serve over fresh cucumber salad with mint raita.",
        ],
        "ingredients": [("paneer", 110), ("plain_yogurt", 90), ("cucumber", 90), ("tomato", 60), ("onion", 40), ("olive_oil", 5)],
    },
    {
        "slug": "nihari-light-trimmed-roti",
        "name": "Light homestyle beef stew (nihari-style) with 1 chapati",
        "slot": "dinner",
        "cost_tier": "medium",
        "prep_min": 40,
        "image_url": _wm("Beef_Nihari.JPG"),
        "tags": ["desi", "high_protein"],
        "guidance_note": "Preparing at home with lean meat, minimal oil, and 1 chapati (instead of refined naan) keeps evening excursions smaller.",
        "steps": [
            "Slow-simmer 130g lean beef with nihari spices and ginger.",
            "Thicken lightly with 10g whole-wheat atta and serve with 1 chapati and fresh salad.",
        ],
        "ingredients": [("lean_beef_keema", 130), ("whole_wheat_flour", 45), ("onion", 30), ("cucumber", 60), ("olive_oil", 5)],
    },
    {
        "slug": "dal-palak-chapati",
        "name": "Dal palak (spinach lentils) with 1 chapati & raita",
        "slot": "dinner",
        "cost_tier": "low",
        "prep_min": 25,
        "image_url": _wm("Roti_%2C_Chany_ki_Dal_and_Salad_with_cut_Onion_and_Tomatoes.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget", "low_gl"],
        "guidance_note": "High-fibre dinner pairing leafy greens with lentils and modest whole-wheat roti.",
        "steps": [
            "Simmer 140g cooked masoor daal with 120g chopped fresh spinach and garlic tadka.",
            "Serve with 1 whole-wheat chapati and plain dahi.",
        ],
        "ingredients": [("masoor_daal_cooked", 140), ("spinach_palak", 120), ("whole_wheat_flour", 40), ("plain_yogurt", 60), ("olive_oil", 5)],
    },

    # --- SNACKS (4) ---
    {
        "slug": "chana-chaat-snack",
        "name": "Evening chana chaat (boiled chickpeas, tomato & lemon)",
        "slot": "snack",
        "cost_tier": "low",
        "prep_min": 10,
        "image_url": _wm("Chana_Chaat.jpg"),
        "tags": ["vegetarian", "high_fibre", "desi", "budget", "quick", "low_gl"],
        "guidance_note": "Avoid sweet tamarind chutney; lemon juice and chaat masala keep sugar very low.",
        "steps": [
            "Mix 100g boiled chickpeas with diced cucumber, tomato, onion, lemon juice, and chaat masala.",
        ],
        "ingredients": [("kabuli_chana_cooked", 100), ("cucumber", 50), ("tomato", 40), ("onion", 25)],
    },
    {
        "slug": "cucumber-mint-raita-almonds",
        "name": "Cucumber mint raita with a small handful of almonds",
        "slot": "snack",
        "cost_tier": "low",
        "prep_min": 5,
        "image_url": _wm("Raita_with_cucumber_and_mint.jpg"),
        "tags": ["vegetarian", "low_gl", "quick", "budget"],
        "guidance_note": "Low-carb snack between meals when hunger hits without wanting a big glucose rise.",
        "steps": [
            "Stir grated cucumber, fresh mint, and roasted cumin into 120g plain dahi; pair with 14g almonds.",
        ],
        "ingredients": [("plain_yogurt", 120), ("cucumber", 60), ("almonds", 14)],
    },
    {
        "slug": "guava-roasted-chana-snack",
        "name": "Fresh guava with 15g almonds",
        "slot": "snack",
        "cost_tier": "low",
        "prep_min": 5,
        "image_url": _wm("Indian_Fruit_Chaat.jpg"),
        "tags": ["vegetarian", "high_fibre", "low_gl", "quick", "budget"],
        "guidance_note": "Pairing whole fruit with nuts slows sugar entry into the bloodstream.",
        "steps": [
            "Slice 1 medium guava (110g) and sprinkle lightly with chaat masala; eat with 15g almonds.",
        ],
        "ingredients": [("guava", 110), ("almonds", 15)],
    },
    {
        "slug": "hard-boiled-eggs-cucumber",
        "name": "2 spiced boiled eggs with cucumber sticks",
        "slot": "snack",
        "cost_tier": "low",
        "prep_min": 10,
        "image_url": _wm("Masala_Omelette.jpg"),
        "tags": ["high_protein", "low_gl", "quick", "budget"],
        "guidance_note": "Zero-sugar protein snack suitable before evening walks or busy work afternoons.",
        "steps": [
            "Boil 2 eggs, halve and sprinkle black pepper; serve with 80g cucumber slices.",
        ],
        "ingredients": [("egg_whole", 100), ("cucumber", 80)],
    },

    # --- RAMADAN SUHOOR & IFTAR (2) ---
    {
        "slug": "suhoor-dalia-eggs-dahi",
        "name": "Suhoor plate: whole-wheat dalia, 2 boiled eggs & dahi",
        "slot": "suhoor",
        "cost_tier": "low",
        "prep_min": 15,
        "image_url": _wm("Aloo_paratha.jpg"),
        "tags": ["ramadan_friendly", "high_fibre", "high_protein", "desi", "budget"],
        "guidance_note": "Slow-release cracked wheat dalia plus eggs and yogurt helps sustain daytime energy and reduce mid-morning dips during Ramadan (IDF-DAR guidance).",
        "steps": [
            "Cook 40g broken wheat dalia in water and 100ml low-fat milk (unsweetened).",
            "Pair with 2 boiled eggs, 100g plain dahi, and 2 glasses of water.",
        ],
        "ingredients": [("broken_wheat_dalia", 40), ("milk_lowfat", 100), ("egg_whole", 100), ("plain_yogurt", 100)],
    },
    {
        "slug": "iftar-1-date-chana-tikka",
        "name": "Balanced Iftar: 1 khajoor, chana chaat & grilled chicken tikka",
        "slot": "iftar",
        "cost_tier": "medium",
        "prep_min": 20,
        "image_url": _wm("Chana_Chaat.jpg"),
        "tags": ["ramadan_friendly", "high_protein", "high_fibre", "desi"],
        "guidance_note": "Break the fast with 1 date (~18g) and water, followed by high-fibre chana chaat and grilled protein instead of deep-fried samosas and sugary drinks.",
        "steps": [
            "Open the fast with 1 Medjool date and water.",
            "Have 120g kala chana chaat and 120g grilled chicken tikka with cucumber salad.",
        ],
        "ingredients": [("dates_medjool", 18), ("kala_chana_cooked", 120), ("chicken_breast", 120), ("cucumber", 70), ("tomato", 50)],
    },
]


@dataclass(frozen=True)
class ComputedNutrition:
    carbs_g: float
    sugar_g: float
    fibre_g: float
    protein_g: float
    fat_g: float
    kcal: float
    estimated_gl: float
    gl_band: str


def compute_recipe_nutrition(ingredients_with_foods: Iterable[tuple[float, FoodItem]]) -> ComputedNutrition:
    """Compute exact per-portion nutrients by summing (grams / 100) * food_item values."""
    carbs = 0.0
    sugar = 0.0
    fibre = 0.0
    protein = 0.0
    fat = 0.0
    kcal = 0.0
    weighted_gi_num = 0.0
    net_carbs_total = 0.0

    for grams, food in ingredients_with_foods:
        factor = grams / 100.0
        c = factor * food.carbs_g_per_100g
        s = factor * food.sugar_g_per_100g
        f = factor * food.fibre_g_per_100g
        p = factor * food.protein_g_per_100g
        ft = factor * food.fat_g_per_100g
        k = factor * food.kcal_per_100g
        carbs += c
        sugar += s
        fibre += f
        protein += p
        fat += ft
        kcal += k

        net_c = max(0.0, c - f)
        if food.gi is not None and net_c > 0:
            weighted_gi_num += net_c * (food.gi / 100.0)
        elif net_c > 0:
            weighted_gi_num += net_c * 0.45
        net_carbs_total += net_c

    gl = round(weighted_gi_num, 1)
    if gl <= 10.0:
        band = "Low"
    elif gl <= 19.0:
        band = "Medium"
    else:
        band = "High"

    return ComputedNutrition(
        carbs_g=round(carbs, 1),
        sugar_g=round(sugar, 1),
        fibre_g=round(fibre, 1),
        protein_g=round(protein, 1),
        fat_g=round(fat, 1),
        kcal=round(kcal, 0),
        estimated_gl=gl,
        gl_band=band,
    )


def ensure_food_and_recipe_catalog(db: Session) -> dict[str, Recipe]:
    """Idempotently seed USDA/PK FoodItems and 30 curated desi recipes; returns {slug: Recipe}."""
    existing_foods = {f.slug: f for f in db.scalars(select(FoodItem)).all()}
    for fdef in FOOD_ITEM_DEFS:
        if fdef["slug"] not in existing_foods:
            item = FoodItem(**fdef)
            db.add(item)
            db.flush()
            existing_foods[item.slug] = item

    existing_recipes = {r.slug: r for r in db.scalars(select(Recipe)).all()}
    for rdef in RECIPE_DEFS:
        if rdef["slug"] in existing_recipes:
            existing_r = existing_recipes[rdef["slug"]]
            if existing_r.image_url != rdef["image_url"]:
                existing_r.image_url = rdef["image_url"]
            continue
        recipe = Recipe(
            slug=rdef["slug"],
            name=rdef["name"],
            cuisine="Pakistani",
            slot=rdef["slot"],
            cost_tier=rdef["cost_tier"],
            prep_min=rdef["prep_min"],
            servings=1,
            steps=rdef["steps"],
            image_url=rdef["image_url"],
            image_license="Wikimedia Commons CC",
            image_is_illustration=False,
            tags=rdef["tags"],
            guidance_note=rdef["guidance_note"],
        )
        db.add(recipe)
        db.flush()
        for food_slug, grams in rdef["ingredients"]:
            food_obj = existing_foods[food_slug]
            db.add(RecipeIngredient(recipe_id=recipe.id, food_item_id=food_obj.id, grams=float(grams)))
        existing_recipes[recipe.slug] = recipe

    db.commit()
    return existing_recipes
