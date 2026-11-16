"""012_v2_chat_memory_recipes_preferences

Revision ID: 6d04b1f70012
Revises: 5c93a0e60011
Create Date: 2026-11-16 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "6d04b1f70012"
down_revision: Union[str, Sequence[str], None] = "5c93a0e60011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=sa.text("'Conversation with Cadie'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_chat_sessions_patient_cohort",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_chat_sessions_patient_updated", "chat_sessions", ["patient_id", sa.text("updated_at DESC")])

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intents", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cards", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("safety_passed", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('patient', 'cadie')", name="ck_chat_messages_role"),
    )
    op.create_index("idx_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("idx_chat_messages_session_time", "chat_messages", ["session_id", "created_at"])

    op.create_table(
        "patient_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_type", sa.String(length=32), nullable=False),
        sa.Column("fact_type", sa.String(length=32), nullable=False, server_default=sa.text("'other'")),
        sa.Column("fact_text", sa.Text(), nullable=False),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default=sa.text("'high'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_patient_memory_patient_cohort",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "fact_type IN ('diet_preference', 'routine', 'medical_context', 'goal', 'other')",
            name="ck_patient_memory_fact_type",
        ),
        sa.CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_patient_memory_confidence"),
    )
    op.create_index("idx_patient_memory_active", "patient_memory", ["patient_id", "deleted_at"])

    op.create_table(
        "food_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_ur", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'usda_fdc'")),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("carbs_g_per_100g", sa.Float(), nullable=False),
        sa.Column("sugar_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fibre_g_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_g_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_g_per_100g", sa.Float(), nullable=False),
        sa.Column("kcal_per_100g", sa.Float(), nullable=False),
        sa.Column("gi", sa.Float(), nullable=True),
        sa.CheckConstraint("source IN ('usda_fdc', 'pk_curated', 'cgmacros')", name="ck_food_items_source"),
    )

    op.create_table(
        "recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("cuisine", sa.String(length=64), nullable=False, server_default=sa.text("'Pakistani'")),
        sa.Column("slot", sa.String(length=32), nullable=False),
        sa.Column("cost_tier", sa.String(length=16), nullable=False, server_default=sa.text("'low'")),
        sa.Column("prep_min", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("servings", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("image_url", sa.String(length=512), nullable=False),
        sa.Column("image_license", sa.String(length=128), nullable=False, server_default=sa.text("'Wikimedia Commons CC'")),
        sa.Column("image_is_illustration", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("guidance_note", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.CheckConstraint("slot IN ('breakfast', 'lunch', 'dinner', 'snack', 'suhoor', 'iftar')", name="ck_recipes_slot"),
        sa.CheckConstraint("cost_tier IN ('low', 'medium', 'high')", name="ck_recipes_cost_tier"),
    )

    op.create_table(
        "recipe_ingredients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grams", sa.Float(), nullable=False),
        sa.Column("prep_note", sa.String(length=128), nullable=True),
        sa.CheckConstraint("grams > 0", name="ck_recipe_ingredients_grams_pos"),
    )
    op.create_index("idx_recipe_ingredients_recipe", "recipe_ingredients", ["recipe_id"])

    op.create_table(
        "meal_food_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("meal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("meals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("food_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("food_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipe_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("grams", sa.Float(), nullable=True),
    )
    op.create_index("idx_meal_food_links_meal", "meal_food_links", ["meal_id"])

    op.create_table(
        "medication_stock",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("medication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("medications.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("units_on_hand", sa.Float(), nullable=False, server_default=sa.text("30")),
        sa.Column("daily_units", sa.Float(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("units_on_hand >= 0", name="ck_med_stock_units_nonneg"),
        sa.CheckConstraint("daily_units > 0", name="ck_med_stock_daily_pos"),
    )

    op.create_table(
        "patient_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("cohort_type", sa.String(length=32), nullable=False),
        sa.Column("vegetarian", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allergies", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("budget_tier", sa.String(length=16), nullable=False, server_default=sa.text("'low'")),
        sa.Column("city", sa.String(length=64), nullable=False, server_default=sa.text("'Lahore'")),
        sa.Column("gentle_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=sa.text("'en'")),
        sa.Column("target_low_mg_dl", sa.Float(), nullable=False, server_default=sa.text("70")),
        sa.Column("target_high_mg_dl", sa.Float(), nullable=False, server_default=sa.text("180")),
        sa.Column("emergency_contact_name", sa.String(length=128), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_patient_prefs_patient_cohort",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("patient_id", name="uq_patient_prefs_patient"),
        sa.CheckConstraint("budget_tier IN ('low', 'medium', 'high')", name="ck_patient_prefs_budget"),
        sa.CheckConstraint("target_low_mg_dl >= 50 AND target_low_mg_dl < target_high_mg_dl", name="ck_patient_prefs_targets"),
    )


def downgrade() -> None:
    op.drop_table("patient_preferences")
    op.drop_table("medication_stock")
    op.drop_index("idx_meal_food_links_meal", table_name="meal_food_links")
    op.drop_table("meal_food_links")
    op.drop_index("idx_recipe_ingredients_recipe", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    op.drop_table("recipes")
    op.drop_table("food_items")
    op.drop_index("idx_patient_memory_active", table_name="patient_memory")
    op.drop_table("patient_memory")
    op.drop_index("idx_chat_messages_session_time", table_name="chat_messages")
    op.drop_index("idx_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("idx_chat_sessions_patient_updated", table_name="chat_sessions")
    op.drop_table("chat_sessions")
