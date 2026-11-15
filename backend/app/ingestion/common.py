from datetime import date, datetime, timedelta, timezone, tzinfo
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Sequence
import zipfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

MMOL_L_TO_MG_DL = 18.0182
MIN_PHYSIOLOGICAL_GLUCOSE_MG_DL = 10.0
MAX_PHYSIOLOGICAL_GLUCOSE_MG_DL = 1500.0
PREPROCESSING_VERSION = "v1.2.0"

TimestampSemanticsType = Literal["utc_exact", "real_world_local", "date_shifted_relative"]
TimezoneBasisType = Literal[
    "source_confirmed",
    "assumed_study_location",
    "unknown",
    "not_applicable_relative",
]
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


def resolve_iana_tz(iana_name: str) -> tzinfo:
    """Resolve an IANA timezone name (e.g. 'Asia/Shanghai'), with safe fallback on Windows without tzdata."""
    try:
        return ZoneInfo(iana_name)
    except ZoneInfoNotFoundError:
        if iana_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        if iana_name in {"UTC", "Etc/UTC"}:
            return timezone.utc
        raise


SHANGHAI_TZ: tzinfo = resolve_iana_tz("Asia/Shanghai")


class RejectedRecord(BaseModel):
    source_record_id: str
    reason: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class IngestionSummary(BaseModel):
    dataset_import_id: str
    dataset_name: str
    dataset_version: str
    dataset_doi: str | None = None
    source_url: str | None = None
    license_identifier: str
    license_url: str | None = None
    preprocessing_version: str
    source_file_checksum: str | None = None
    directory_manifest_checksum: str | None = None
    input_payload_checksum: str | None = None
    records_accepted: int
    records_rejected: int
    rejection_reasons: dict[str, int]
    rejected_samples: list[RejectedRecord]
    participants_ingested: int
    excluded_non_t2d_participants: list[str] = Field(default_factory=list)
    observation_provenance_counts: dict[str, int] = Field(default_factory=dict)
    timestamp_semantics: str = "utc_exact"
    timezone_basis: str = "source_confirmed"


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
    """Compute SHA-256 strictly over the original on-disk bytes of a SINGLE regular file.

    Returns ``None`` when ``source`` is ``None``.
    Raises ``ValueError`` if passed in-memory bytes/objects, a non-existent path,
    or a directory path (directories must use ``compute_directory_manifest_checksum``).
    """
    if source is None:
        return None
    if isinstance(source, (bytes, bytearray, dict, list)):
        raise ValueError(
            "source_file_checksum requires an existing regular file path; use compute_input_payload_checksum for in-memory payloads."
        )
    path = Path(source)
    if not path.exists():
        raise ValueError(f"source_file_checksum path does not exist on disk: {path}")
    if path.is_dir():
        raise ValueError(
            f"source_file_checksum requires a regular file, not a directory ({path}); use compute_directory_manifest_checksum for directories."
        )
    if not path.is_file():
        raise ValueError(f"Unsupported source_file_checksum target (not a regular file): {path}")

    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_directory_manifest_checksum(directory: Path | str | None) -> str | None:
    """Compute SHA-256 over sorted relative file paths and file bytes within a directory.

    Stored in ``DatasetImport.directory_manifest_checksum`` and never conflated with
    ``source_file_checksum``.
    """
    if directory is None:
        return None
    if isinstance(directory, (bytes, bytearray, dict, list)):
        raise ValueError("directory_manifest_checksum requires an existing directory path on disk.")
    path = Path(directory)
    if not path.exists():
        raise ValueError(f"directory_manifest_checksum path does not exist on disk: {path}")
    if not path.is_dir():
        raise ValueError(
            f"directory_manifest_checksum requires a directory path, not a regular file ({path}); use compute_source_file_checksum for single files."
        )

    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"directory_manifest_checksum directory contains no regular files: {path}")

    hasher = hashlib.sha256()
    for child in files:
        rel = child.relative_to(path).as_posix().encode("utf-8")
        hasher.update(rel)
        hasher.update(b"\x00")
        with child.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        hasher.update(b"\x00")
    return hasher.hexdigest()


def resolve_source_checksums(
    source_path: Path | str | None,
) -> tuple[str | None, str | None]:
    """Return ``(source_file_checksum, directory_manifest_checksum)`` for an optional disk path."""
    if source_path is None:
        return None, None
    path = Path(source_path)
    if not path.exists():
        raise ValueError(f"Source path does not exist on disk: {path}")
    if path.is_dir():
        return None, compute_directory_manifest_checksum(path)
    return compute_source_file_checksum(path), None


def _canonicalize_payload_value(value: Any) -> Any:
    """Normalize arbitrary Python values into a deterministic JSON-compatible structure.

    - Dict keys are coerced to ``str`` and sorted by ``json.dumps(..., sort_keys=True)``.
    - List/tuple order (row order) is preserved as semantically significant.
    - ``datetime`` and ``date`` objects are formatted via ``.isoformat()``.
    - ``float`` values normalize ``NaN``/``Inf`` to ``None`` and ``-0.0`` to ``0.0``.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return 0.0 if value == 0.0 else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _canonicalize_payload_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_payload_value(item) for item in value]
    return str(value)


def compute_input_payload_checksum(payload: Any) -> str:
    """Compute SHA-256 of a documented canonical UTF-8 JSON serialization of structured input.

    Canonicalization contract:
    - Dictionary key order is normalized recursively (``sort_keys=True``).
    - List / row order is intentionally preserved (reordering input rows changes the checksum).
    - ``datetime`` / ``date`` instances serialize via ISO-8601 ``.isoformat()``.
    - ``NaN`` and ``Infinity`` float values normalize to JSON ``null`` (``allow_nan=False``).
    - Unicode strings are encoded directly as UTF-8 (``ensure_ascii=False``) with compact
      separators ``(',', ':')``.
    """
    if isinstance(payload, bytes):
        canonical_bytes = payload
    else:
        normalized = _canonicalize_payload_value(payload)
        canonical_json = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        canonical_bytes = canonical_json.encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def compute_sha256(source: Path | str | bytes) -> str:
    """Low-level SHA-256 helper for raw bytes or existing file/directory paths on disk.

    Raises ``ValueError`` if a ``Path`` or ``str`` path does not exist on disk
    (never falls back to hashing the path string).
    """
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    path = Path(source)
    if not path.exists():
        raise ValueError(f"compute_sha256 path does not exist on disk: {path}")
    if path.is_dir():
        checksum = compute_directory_manifest_checksum(path)
    else:
        checksum = compute_source_file_checksum(path)
    assert checksum is not None
    return checksum


def extract_zip_safely(archive_path: Path | str, dest_dir: Path | str) -> list[Path]:
    """Validate and extract a ZIP archive into ``dest_dir`` with strict zip-slip protection.

    All archive entries are validated BEFORE any bytes are extracted:
    - Rejects absolute POSIX or Windows paths and Windows drive letters.
    - Rejects any ``..`` path traversal components.
    - Rejects any member whose resolved destination escapes ``dest_dir.resolve()``.
    - Skips macOS ``__MACOSX`` metadata and Office temporary lock files (``~$``).
    """
    arch = Path(archive_path)
    if not arch.exists() or not arch.is_file():
        raise ValueError(f"ZIP archive does not exist or is not a regular file: {arch}")

    dest_root = Path(dest_dir).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    extracted_files: list[Path] = []
    with zipfile.ZipFile(arch, "r") as zf:
        members = zf.infolist()
        validated_targets: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in members:
            raw_name = info.filename
            norm_posix = raw_name.replace("\\", "/")
            posix_path = PurePosixPath(norm_posix)
            win_path = PureWindowsPath(raw_name)

            if (
                raw_name.startswith(("/", "\\"))
                or posix_path.is_absolute()
                or win_path.is_absolute()
                or bool(win_path.drive)
                or ".." in posix_path.parts
                or ".." in win_path.parts
            ):
                raise ValueError(
                    f"zip_slip_path_traversal_detected: unsafe archive entry {raw_name!r}"
                )

            target_path = (dest_root / Path(*posix_path.parts)).resolve()
            if not target_path.is_relative_to(dest_root):
                raise ValueError(
                    f"zip_slip_path_traversal_detected: entry {raw_name!r} escapes {dest_root}"
                )

            if info.is_dir() or raw_name.endswith("/"):
                continue
            if "__MACOSX" in posix_path.parts or posix_path.name.startswith("~$"):
                continue
            validated_targets.append((info, target_path))

        for idx, (info, target_path) in enumerate(validated_targets):
            # Safely handle non-ASCII filenames on Windows filesystems if needed
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, target_path.open("wb") as dst:
                    for chunk in iter(lambda: src.read(65536), b""):
                        dst.write(chunk)
                extracted_files.append(target_path)
            except OSError:
                fallback_rel = Path(*[
                    p if p.isascii() else f"dir_{i}"
                    for i, p in enumerate(target_path.relative_to(dest_root).parts[:-1])
                ]) / (
                    target_path.name
                    if target_path.name.isascii()
                    else f"file_{idx}{target_path.suffix}"
                )
                safe_target = (dest_root / fallback_rel).resolve()
                safe_target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, safe_target.open("wb") as dst:
                    for chunk in iter(lambda: src.read(65536), b""):
                        dst.write(chunk)
                extracted_files.append(safe_target)

    return extracted_files


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if type(value).__name__ == "NaTType":
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


def _parse_raw_datetime(value: Any) -> datetime:
    """Parse a datetime object or string without attaching a default timezone."""
    if is_missing_value(value):
        raise ValueError("invalid_timestamp")

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
            return datetime.fromisoformat(iso_text)
        except ValueError:
            pass

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
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise ValueError("invalid_timestamp")
    raise ValueError("invalid_timestamp")


def parse_utc_timestamp(
    value: Any,
    *,
    default_tz: tzinfo = timezone.utc,
) -> datetime:
    """Parse a timestamp value and normalize to timezone-aware UTC."""
    dt = _parse_raw_datetime(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt.astimezone(timezone.utc)


def parse_timestamp_with_semantics(
    value: Any,
    *,
    semantics: TimestampSemanticsType = "utc_exact",
    local_tz: tzinfo | None = None,
    assumed_iana_tz: str | None = None,
) -> tuple[datetime, str, TimestampSemanticsType, TimezoneBasisType]:
    """Parse a timestamp while preserving the raw string, timestamp semantics, and timezone basis.

    Returns ``(utc_datetime, raw_timestamp_str, timestamp_semantics, timezone_basis)``:
    - When ``semantics == 'date_shifted_relative'``:
      Uses a neutral ``+00:00`` epoch reference without inferring any real-world timezone,
      and marks ``timezone_basis = 'not_applicable_relative'``.
    - When the raw value includes an explicit timezone offset (e.g., ``Z``, ``+08:00``, or
      timezone-aware ``datetime``):
      Marks ``timezone_basis = 'source_confirmed'``.
    - When the raw value is a naive local timestamp without an offset and ``assumed_iana_tz``
      (e.g., ``'Asia/Shanghai'``) or ``local_tz`` is supplied from study location context:
      Attaches that timezone, converts to UTC, and marks ``timezone_basis = 'assumed_study_location'``.
    - When the raw value is naive and no timezone is confirmed or assumed:
      Uses UTC as a neutral carrier and marks ``timezone_basis = 'unknown'``.
    """
    if is_missing_value(value):
        raise ValueError("invalid_timestamp")
    raw_str = value.isoformat() if isinstance(value, datetime) else str(value).strip()
    dt = _parse_raw_datetime(value)

    if semantics == "date_shifted_relative":
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), raw_str[:64], "date_shifted_relative", "not_applicable_relative"

    if dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None:
        return dt.astimezone(timezone.utc), raw_str[:64], semantics, "source_confirmed"

    # Naive timestamp without explicit offset in source
    if assumed_iana_tz:
        tz_obj = resolve_iana_tz(assumed_iana_tz)
        dt_aware = dt.replace(tzinfo=tz_obj)
        return dt_aware.astimezone(timezone.utc), raw_str[:64], semantics, "assumed_study_location"

    if local_tz is not None:
        dt_aware = dt.replace(tzinfo=local_tz)
        basis: TimezoneBasisType = (
            "assumed_study_location" if semantics == "real_world_local" else "unknown"
        )
        return dt_aware.astimezone(timezone.utc), raw_str[:64], semantics, basis

    dt_utc = dt.replace(tzinfo=timezone.utc)
    return dt_utc, raw_str[:64], semantics, "unknown"


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
