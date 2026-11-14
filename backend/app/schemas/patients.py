import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


RetentionPolicyType = Literal[
    "30_days",
    "90_days",
    "180_days",
    "365_days",
    "custom_days",
    "indefinite_until_revoked",
    "research_archive",
    "dataset_license_bound",
]

POLICY_DEFAULT_DAYS: dict[str, int] = {
    "30_days": 30,
    "90_days": 90,
    "180_days": 180,
    "365_days": 365,
}


class PatientCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    age: int | None = Field(default=None, ge=1, le=120)
    sex: str | None = Field(default=None, max_length=32)
    diabetes_type: Literal["T2D", "T1D", "prediabetes", "healthy", "unknown"] = "T2D"
    height_cm: float | None = Field(default=None, gt=30, lt=260)
    weight_kg: float | None = Field(default=None, gt=15, lt=400)
    dietary_restrictions: list[str] = Field(default_factory=list)
    cultural_cuisine_pref: str | None = Field(default=None, max_length=128)
    consent_granted: bool
    consent_version: str = Field(min_length=1, max_length=64)
    retention_policy: RetentionPolicyType = "365_days"
    retention_days: int | None = Field(default=365, ge=30, le=3650)

    @field_validator("consent_granted")
    @classmethod
    def require_explicit_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit consent_granted=true is required for patient onboarding.")
        return value


class PatientUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    weight_kg: float | None = Field(default=None, gt=15, lt=400)
    dietary_restrictions: list[str] | None = None
    cultural_cuisine_pref: str | None = Field(default=None, max_length=128)
    retention_policy: RetentionPolicyType | None = None
    retention_days: int | None = Field(default=None, ge=30, le=3650)


class PatientOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    cohort_type: str
    display_name: str
    age: int | None
    sex: str | None
    diabetes_type: str
    height_cm: float | None
    weight_kg: float | None
    dietary_restrictions: list[str]
    cultural_cuisine_pref: str | None
    consent_granted: bool
    consent_version: str | None
    consent_granted_at: datetime | None
    retention_policy: str
    retention_days: int | None
    source_dataset: str
    created_at: datetime

    model_config = {"from_attributes": True}
