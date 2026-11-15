from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field

MMOL_L_TO_MG_DL = 18.0182
MIN_PHYSIOLOGICAL_GLUCOSE_MG_DL = 10.0
MAX_PHYSIOLOGICAL_GLUCOSE_MG_DL = 1500.0
PREPROCESSING_VERSION = "v1.1.0"

TimestampSemanticsType = Literal["utc_exact", "real_world_local", "date_shifted_relative"]
ObservationProvenanceType = Literal["native", "interpolated", "derived", "unknown"]

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
    license_identifier: str
    preprocessing_version: str
    source_file_checksum: str | None = None
    input_payload_checksum: str | None = None
    records_accepted: int
    records_rejected: int
    rejection_reasons: dict[str, int]
    rejected_samples: list[RejectedRecord]
    participants_ingested: int
    excluded_non_t2d_participants: list[str] = Field(default_factory=list)
    observation_provenance_counts: dict[str, int] = Field(default_factory=dict)
    timestamp_semantics: str = "utc_exact"


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


def compute_source_file_checksum(source: Path | str | None) -> str | None:
    """Compute SHA-256 strictly over original on-disk file bytes (or directory of files).

    Returns ``None`` when ``source`` is ``None``.
    Raises ``ValueError`` if passed in-memory bytes/objects or a non-existent path,
    preventing DataFrame or payload serializations from ever being labeled as
    ``source_file_checksum``.
    """
    if source is None:
        return None
    if isinstance(source, (bytes, bytearray, dict, list)):
        raise ValueError(
            "source_file_checksum requires an existing on-disk file path; use compute_input_payload_checksum for in-memory payloads."
        )
    path = Path(source)
    if not path.exists():
        raise ValueError(f"source_file_checksum path does not exist on disk: {path}")

    hasher = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        if not files:
            raise ValueError(f"source_file_checksum directory contains no files: {path}")
        for child in files:
            rel = child.relative_to(path).as_posix().encode("utf-8")
            hasher.update(rel)
            with child.open("rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    hasher.update(chunk)
        return hasher.hexdigest()

    raise ValueError(f"Unsupported source_file_checksum target: {path}")


def compute_input_payload_checksum(payload: Any) -> str:
    """Compute SHA-256 of a documented canonical JSON serialization of structured input.

    Canonical rules:
    - UTF-8 encoded JSON with ``sort_keys=True``, ``separators=(',', ':')``,
      and ``default=str`` for timestamps/UUIDs/paths.
    """
    if isinstance(payload, bytes):
        canonical_bytes = payload
    else:
        canonical_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        canonical_bytes = canonical_json.encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def compute_sha256(source: Path | str | bytes) -> str:
    """Low-level SHA-256 helper for raw bytes or existing file paths."""
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    path = Path(source)
    if path.exists():
        checksum = compute_source_file_checksum(path)
        assert checksum is not None
        return checksum
    return compute_input_payload_checksum(str(source))


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
    """Validate and normalize a glucose value, returning (glucose_mg_dl, raw_float, canonical_unit)."""
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
    """Parse a timestamp value and normalize to timezone-aware UTC."""
    if is_missing_value(value):
        raise ValueError("invalid_timestamp")

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        dt = None
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


def parse_timestamp_with_semantics(
    value: Any,
    *,
    semantics: TimestampSemanticsType = "utc_exact",
    local_tz: timezone = timezone.utc,
) -> tuple[datetime, str, TimestampSemanticsType]:
    """Parse a timestamp while preserving the raw supplied string and explicit timestamp semantics.

    When ``semantics == 'date_shifted_relative'`` (e.g., CGMacros on PhysioNet):
    - Preserves the original supplied timestamp string verbatim in ``raw_timestamp``.
    - Uses a neutral ``+00:00`` epoch reference without inferring any real-world timezone,
      strictly preserving relative elapsed intervals and chronological ordering.
    """
    if is_missing_value(value):
        raise ValueError("invalid_timestamp")
    raw_str = value.isoformat() if isinstance(value, datetime) else str(value).strip()
    carrier_tz = timezone.utc if semantics == "date_shifted_relative" else local_tz
    parsed_dt = parse_utc_timestamp(value, default_tz=carrier_tz)
    return parsed_dt, raw_str[:64], semantics


def validate_calendar_date_comparability(
    timestamp_semantics_values: Sequence[str],
    *,
    dataset_names: Sequence[str] | None = None,
) -> None:
    """Block cross-dataset or real-world calendar-date alignment when date_shifted_relative is present."""
    semantics_set = {str(s).strip() for s in timestamp_semantics_values if s}
    if "date_shifted_relative" in semantics_set:
        if len(semantics_set) > 1 or (dataset_names and len(set(dataset_names)) > 1):
            raise ValueError("calendar_date_comparison_forbidden_for_date_shifted_relative")
        raise ValueError("calendar_date_comparison_forbidden_for_date_shifted_relative")


SHANGHAI_TZ = timezone(timedelta(hours=8))
