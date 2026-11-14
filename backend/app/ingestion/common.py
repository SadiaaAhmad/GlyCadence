from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MMOL_L_TO_MG_DL = 18.0182
MIN_PHYSIOLOGICAL_GLUCOSE_MG_DL = 10.0
MAX_PHYSIOLOGICAL_GLUCOSE_MG_DL = 1500.0
PREPROCESSING_VERSION = "v1.0.0"

MISSING_SENTINELS = {
    "",
    "nan",
    "none",
    "null",
    "na",
    "n/a",
    "data not available",
    "not available",
    "-",
    "--",
}


class RejectedRecord(BaseModel):
    source_record_id: str
    reason: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class IngestionSummary(BaseModel):
    dataset_import_id: str
    dataset_name: str
    dataset_version: str
    preprocessing_version: str
    source_file_checksum: str
    records_accepted: int
    records_rejected: int
    rejection_reasons: dict[str, int]
    rejected_samples: list[RejectedRecord]
    participants_ingested: int
    excluded_non_t2d_participants: list[str] = Field(default_factory=list)


class RejectionTracker:
    """Tracks accepted and rejected rows with structured rejection reasons."""

    def __init__(self, max_samples: int = 100) -> None:
        self.accepted_count: int = 0
        self.rejected_count: int = 0
        self.reasons: dict[str, int] = {}
        self.samples: list[RejectedRecord] = []
        self._max_samples = max_samples

    def accept(self, count: int = 1) -> None:
        self.accepted_count += count

    def reject(
        self,
        *,
        source_record_id: str,
        reason: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        self.rejected_count += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1
        if len(self.samples) < self._max_samples:
            sanitized = {}
            if raw_payload:
                for k, v in raw_payload.items():
                    sanitized[str(k)] = None if v is None else str(v)[:120]
            self.samples.append(
                RejectedRecord(
                    source_record_id=source_record_id,
                    reason=reason,
                    raw_payload=sanitized,
                )
            )

    def to_quality_report(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        report: dict[str, Any] = {
            "records_accepted": self.accepted_count,
            "records_rejected": self.rejected_count,
            "rejection_reasons": dict(self.reasons),
            "rejected_samples": [s.model_dump() for s in self.samples],
        }
        if extra:
            report.update(extra)
        return report


def compute_sha256(source: Path | str | bytes) -> str:
    """Compute deterministic SHA-256 hex digest for a file, directory of files, or raw bytes."""
    hasher = hashlib.sha256()
    if isinstance(source, bytes):
        hasher.update(source)
        return hasher.hexdigest()

    path = Path(source)
    if path.is_file():
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            rel = child.relative_to(path).as_posix().encode("utf-8")
            hasher.update(rel)
            with child.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
        return hasher.hexdigest()

    # Fallback for in-memory identifier strings
    hasher.update(str(source).encode("utf-8"))
    return hasher.hexdigest()


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    if isinstance(value, str) and value.strip().lower() in MISSING_SENTINELS:
        return True
    return False


def normalize_glucose_unit(unit: str | None) -> str:
    if unit is None or not str(unit).strip():
        raise ValueError("invalid_unit")
    cleaned = str(unit).strip().lower().replace(" ", "")
    if cleaned in {"mg/dl", "mgdl"}:
        return "mg/dL"
    if cleaned in {"mmol/l", "mmoll", "mmol"}:
        return "mmol/L"
    raise ValueError("invalid_unit")


def normalize_glucose_reading(
    raw_value: Any,
    raw_unit: str = "mg/dL",
) -> tuple[float, float, str]:
    """Validate and normalize a glucose value, returning (glucose_mg_dl, raw_float, canonical_unit).

    Raises ValueError with reason code ('missing_glucose_value', 'invalid_glucose_number',
    'invalid_unit', or 'out_of_physiological_range').
    """
    if is_missing_value(raw_value):
        raise ValueError("missing_glucose_value")

    canonical_unit = normalize_glucose_unit(raw_unit)

    try:
        numeric_raw = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_glucose_number") from exc

    if math.isnan(numeric_raw) or math.isinf(numeric_raw):
        raise ValueError("invalid_glucose_number")

    if canonical_unit == "mmol/L":
        glucose_mg_dl = round(numeric_raw * MMOL_L_TO_MG_DL, 2)
    else:
        glucose_mg_dl = round(numeric_raw, 2)

    if (
        glucose_mg_dl < MIN_PHYSIOLOGICAL_GLUCOSE_MG_DL
        or glucose_mg_dl > MAX_PHYSIOLOGICAL_GLUCOSE_MG_DL
    ):
        raise ValueError("out_of_physiological_range")

    return glucose_mg_dl, round(numeric_raw, 4), canonical_unit


def parse_utc_timestamp(
    value: Any,
    *,
    default_tz: timezone = timezone.utc,
) -> datetime:
    """Parse a timestamp value and normalize to timezone-aware UTC.

    Raises ValueError('invalid_timestamp') if unparseable.
    """
    if is_missing_value(value):
        raise ValueError("invalid_timestamp")

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        dt = None
        # Try ISO-8601 first
        try:
            iso_text = text.replace("Z", "+00:00") if text.endswith("Z") else text
            dt = datetime.fromisoformat(iso_text)
        except ValueError:
            pass

        if dt is None:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError("invalid_timestamp")
    else:
        raise ValueError("invalid_timestamp")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)


SHANGHAI_TZ = timezone(timedelta(hours=8))
