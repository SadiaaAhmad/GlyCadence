import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Conversation with Cadie")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_chat_sessions_patient_cohort",
            ondelete="CASCADE",
        ),
        Index("idx_chat_sessions_patient_updated", "patient_id", text("updated_at DESC")),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intents: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL"), nullable=True
    )
    cards: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    safety_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("role IN ('patient', 'cadie')", name="ck_chat_messages_role"),
        Index("idx_chat_messages_session_time", "session_id", "created_at"),
    )


class PatientMemory(Base):
    __tablename__ = "patient_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="high")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_patient_memory_patient_cohort",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "fact_type IN ('diet_preference', 'routine', 'medical_context', 'goal', 'other')",
            name="ck_patient_memory_fact_type",
        ),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_patient_memory_confidence",
        ),
        Index("idx_patient_memory_active", "patient_id", "deleted_at"),
    )


class FoodItem(Base):
    __tablename__ = "food_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_ur: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="usda_fdc")
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    carbs_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    sugar_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fibre_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    protein_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    fat_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    kcal_per_100g: Mapped[float] = mapped_column(Float, nullable=False)
    gi: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "source IN ('usda_fdc', 'pk_curated', 'cgmacros')",
            name="ck_food_items_source",
        ),
    )


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cuisine: Mapped[str] = mapped_column(String(64), nullable=False, default="Pakistani")
    slot: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    prep_min: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    servings: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    image_url: Mapped[str] = mapped_column(String(512), nullable=False)
    image_license: Mapped[str] = mapped_column(String(128), nullable=False, default="Wikimedia Commons CC")
    image_is_illustration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    guidance_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        CheckConstraint(
            "slot IN ('breakfast', 'lunch', 'dinner', 'snack', 'suhoor', 'iftar')",
            name="ck_recipes_slot",
        ),
        CheckConstraint(
            "cost_tier IN ('low', 'medium', 'high')",
            name="ck_recipes_cost_tier",
        ),
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    food_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_items.id", ondelete="RESTRICT"), nullable=False
    )
    grams: Mapped[float] = mapped_column(Float, nullable=False)
    prep_note: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("grams > 0", name="ck_recipe_ingredients_grams_pos"),
    )


class MealFoodLink(Base):
    __tablename__ = "meal_food_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    food_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food_items.id", ondelete="SET NULL"), nullable=True
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    grams: Mapped[float | None] = mapped_column(Float, nullable=True)


class MedicationStock(Base):
    __tablename__ = "medication_stock"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("medications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    units_on_hand: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    daily_units: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("units_on_hand >= 0", name="ck_med_stock_units_nonneg"),
        CheckConstraint("daily_units > 0", name="ck_med_stock_daily_pos"),
    )


class PatientPreferences(Base):
    __tablename__ = "patient_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    cohort_type: Mapped[str] = mapped_column(String(32), nullable=False)
    vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allergies: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    budget_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    city: Mapped[str] = mapped_column(String(64), nullable=False, default="Lahore")
    gentle_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    target_low_mg_dl: Mapped[float] = mapped_column(Float, nullable=False, default=70.0)
    target_high_mg_dl: Mapped[float] = mapped_column(Float, nullable=False, default=180.0)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(
            ["patient_id", "cohort_type"],
            ["patients.id", "patients.cohort_type"],
            name="fk_patient_prefs_patient_cohort",
            ondelete="CASCADE",
        ),
        UniqueConstraint("patient_id", name="uq_patient_prefs_patient"),
        CheckConstraint("budget_tier IN ('low', 'medium', 'high')", name="ck_patient_prefs_budget"),
        CheckConstraint("target_low_mg_dl >= 50 AND target_low_mg_dl < target_high_mg_dl", name="ck_patient_prefs_targets"),
    )
