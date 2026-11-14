from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatabaseHealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["connected", "database_not_configured", "unsupported_database_version", "database_unavailable"]
    min_required_major_version: int
    detected_major_version: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
