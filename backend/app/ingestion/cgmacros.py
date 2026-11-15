from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.ingestion.common import (
    PREPROCESSING_VERSION,
    IngestionSummary,
    ObservationProvenanceType,
    RejectionTracker,
    compute_input_payload_checksum,
    is_missing_value,
    normalize_glucose_reading,
    parse_timestamp_with_semantics,
    resolve_source_checksums,
)
from app.models import (
    ActivityRecord,
    ClinicalRecord,
    DatasetImport,
    GlucoseReading,
    Meal,
    Patient,
)

DATASET_NAME = "cgmacros"
DEFAULT_DATASET_VERSION = "physionet-cgmacros-v1.0.0"
DEFAULT_DATASET_DOI = "10.13026/3z8q-x658"
DEFAULT_SOURCE_URL = "https://physionet.org/content/cgmacros/1.0.0/"
LICENSE_IDENTIFIER = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
LIBRE_PRO_DEVICE = "FreeStyle_Libre_Pro"
DEXCOM_G6_PRO_DEVICE = "Dexcom_G6_Pro"
LIBRE_SAMPLING_MIN = 15
DEXCOM_SAMPLING_MIN = 5

VALID_PROVENANCES = {"native", "interpolated", "derived", "unknown"}


def classify_cgmacros_glycemic_status(hba1c_pct: float | None, declared_type: str | None = None) -> str:
    """Classify participant glycemic status per CGMacros protocol (Gutierrez-Osuna et al.).

    - HbA1c > 6.4% -> 'T2D' (14 participants in CGMacros)
    - 5.7% <= HbA1c <= 6.4% -> 'prediabetes' (16 participants)
    - HbA1c < 5.7% -> 'healthy' (15 participants)
    """
    if declared_type and not is_missing_value(declared_type):
        cleaned = str(declared_type).strip()
        if cleaned.upper() == "T1D":
            return "T1D"
        if cleaned.upper() == "T2D":
            return "T2D"
        if cleaned.lower() in {"prediabetes", "healthy"}:
            return cleaned.lower()

    if hba1c_pct is None:
        return "unknown"
    if hba1c_pct > 6.4:
        return "T2D"
    if hba1c_pct >= 5.7:
        return "prediabetes"
    return "healthy"


def _load_tabular(source: Path | pd.DataFrame | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(source, list):
        return source
    if isinstance(source, pd.DataFrame):
        return source.to_dict(orient="records")
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path).to_dict(orient="records")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path).to_dict(orient="records")
    raise ValueError(f"Unsupported CGMacros file format: {suffix}")


def _extract_col(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    lower_map = {str(k).strip().lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def _normalize_meal_type(raw_val: Any) -> str:
    if is_missing_value(raw_val):
        return "unknown"
    s = str(raw_val).strip().lower()
    if "breakfast" in s:
        return "breakfast"
    if "lunch" in s:
        return "lunch"
    if "dinner" in s or "supper" in s:
        return "dinner"
    if "snack" in s:
        return "snack"
    return "unknown"


def _format_subject_id(raw_id: Any) -> str:
    text = str(raw_id).strip()
    if text.isdigit():
        return f"CGMacros-{int(text):03d}"
    return text


def query_cgmacros_t2d_cohort(db: Session) -> list[Patient]:
    """Return strictly the T2D research_participant records from CGMacros."""
    return list(
        db.scalars(
            select(Patient)
            .where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == DATASET_NAME,
                Patient.diabetes_type == "T2D",
            )
            .order_by(Patient.external_id.asc())
        ).all()
    )


def _resolve_row_provenance(
    row: dict[str, Any],
    *,
    device_candidates: tuple[str, ...],
    source_verified_native_export: bool,
) -> ObservationProvenanceType:
    """Resolve observation provenance strictly from verifiable source evidence.

    Never classifies a reading as ``'native'`` merely because its timestamp spacing
    matches the nominal sensor cadence (5 min or 15 min). Requires either an explicit
    provenance field on the row or ``source_verified_native_export=True``.
    """
    raw_prov = _extract_col(
        row,
        (*device_candidates, "observation_provenance", "provenance"),
    )
    if not is_missing_value(raw_prov):
        cleaned = str(raw_prov).strip().lower()
        if cleaned in VALID_PROVENANCES:
            return cleaned  # type: ignore[return-value]
    return "native" if source_verified_native_export else "unknown"


def _resolve_checksums(
    bio_source: Path | pd.DataFrame | list[dict[str, Any]],
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    source_file_path: Path | str | None,
) -> tuple[str | None, str | None, str]:
    file_checksum: str | None = None
    dir_checksum: str | None = None
    if source_file_path is not None:
        file_checksum, dir_checksum = resolve_source_checksums(source_file_path)
    elif isinstance(bio_source, (Path, str)) and Path(bio_source).exists():
        all_paths = [
            Path(v)
            for v in participant_sources.values()
            if isinstance(v, (Path, str)) and Path(v).exists()
        ]
        if len(all_paths) == len(participant_sources):
            file_checksum, dir_checksum = resolve_source_checksums(Path(bio_source).parent)

    canonical_payload = {
        "dataset_name": DATASET_NAME,
        "bio": _load_tabular(bio_source) if not isinstance(bio_source, list) else bio_source,
        "participants": {
            str(k): (_load_tabular(v) if not isinstance(v, list) else v)
            for k, v in sorted(participant_sources.items(), key=lambda item: str(item[0]))
        },
    }
    payload_checksum = compute_input_payload_checksum(canonical_payload)
    return file_checksum, dir_checksum, payload_checksum


def ingest_cgmacros(
    db: Session,
    *,
    bio_source: Path | pd.DataFrame | list[dict[str, Any]],
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    source_file_path: Path | str | None = None,
    t2d_only: bool = True,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    dataset_doi: str = DEFAULT_DATASET_DOI,
    source_url: str = DEFAULT_SOURCE_URL,
    preprocessing_version: str = PREPROCESSING_VERSION,
    source_verified_native_export: bool = False,
    native_evidence_reference: str | None = None,
    participant_consent_version: str | None = None,
) -> IngestionSummary:
    """Ingest CGMacros dataset with DOI 10.13026/3z8q-x658, CC BY-NC-SA 4.0 licensing,
    date_shifted_relative semantics, and strict observation provenance tracking.

    Non-negotiable rules enforced:
    - Official PhysioNet v1.0.0 DOI ``10.13026/3z8q-x658`` and license ``CC BY-NC-SA 4.0``
      recorded on ``DatasetImport`` — never stored in ``Patient.consent_version``.
    - Classifies participants via ``bio.csv`` HbA1c (``A1c PDL (Lab) > 6.4%`` => ``T2D``).
    - When ``t2d_only=True`` (default), excludes ``prediabetes`` and ``healthy`` cohorts.
    - Preserves supplied timestamps in ``raw_timestamp`` and marks
      ``timestamp_semantics = 'date_shifted_relative'`` and ``timezone_basis = 'not_applicable_relative'``
      without inferring a real-world timezone.
    - Does NOT classify a reading as ``native`` merely because its interval matches nominal sensor
      cadence (5 min or 15 min). Regularly spaced but unverified readings remain ``unknown``.
    """
    if source_verified_native_export and (
        native_evidence_reference is None or not str(native_evidence_reference).strip()
    ):
        raise ValueError(
            "native_evidence_reference is required when source_verified_native_export=True"
        )
    cleaned_evidence_ref = (
        str(native_evidence_reference).strip() if native_evidence_reference else None
    )
    tracker = RejectionTracker()
    source_file_checksum, directory_manifest_checksum, input_payload_checksum = _resolve_checksums(
        bio_source, participant_sources, source_file_path
    )

    dataset_import = DatasetImport(
        dataset_name=DATASET_NAME,
        dataset_version=dataset_version,
        dataset_doi=dataset_doi,
        source_url=source_url,
        license_identifier=LICENSE_IDENTIFIER,
        license_url=LICENSE_URL,
        source_file_checksum=source_file_checksum,
        directory_manifest_checksum=directory_manifest_checksum,
        input_payload_checksum=input_payload_checksum,
        preprocessing_version=preprocessing_version,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(dataset_import)
    db.flush()

    bio_by_id: dict[str, dict[str, Any]] = {}
    for brow in _load_tabular(bio_source):
        raw_sub = _extract_col(brow, ("subject", "subject_id", "participant_id", "id"))
        if not is_missing_value(raw_sub):
            norm_id = _format_subject_id(raw_sub)
            bio_by_id[norm_id] = brow
            bio_by_id[str(raw_sub).strip()] = brow

    participants_ingested = 0
    excluded_non_t2d: list[str] = []
    provenance_counts: dict[str, int] = {"native": 0, "interpolated": 0, "derived": 0, "unknown": 0}

    for raw_ext_id, ts_source in participant_sources.items():
        ext_id = _format_subject_id(raw_ext_id)
        brow = bio_by_id.get(ext_id) or bio_by_id.get(str(raw_ext_id).strip()) or {}

        raw_a1c = _extract_col(brow, ("a1c pdl (lab)", "hba1c", "a1c", "hba1c_pct"))
        hba1c_val: float | None = None
        if not is_missing_value(raw_a1c):
            try:
                hba1c_val = float(raw_a1c)
            except (TypeError, ValueError):
                pass

        declared_type = _extract_col(brow, ("diabetes_type", "group", "status"))
        diabetes_type = classify_cgmacros_glycemic_status(
            hba1c_val, str(declared_type) if not is_missing_value(declared_type) else None
        )

        if diabetes_type == "T1D":
            tracker.reject(
                source_record_id=f"{ext_id}:bio",
                reason="t1d_cohort_mixing_forbidden",
                raw_payload={"external_id": ext_id, "diabetes_type": diabetes_type},
            )
            continue

        if t2d_only and diabetes_type != "T2D":
            excluded_non_t2d.append(ext_id)
            continue

        raw_age = _extract_col(brow, ("age", "age (years)"))
        age_val = int(float(raw_age)) if not is_missing_value(raw_age) else None

        raw_sex = _extract_col(brow, ("gender", "sex"))
        sex_val: str | None = None
        if not is_missing_value(raw_sex):
            s = str(raw_sex).strip().lower()
            sex_val = "female" if s in {"f", "female"} else ("male" if s in {"m", "male"} else s[:32])

        raw_weight = _extract_col(brow, ("body weight", "weight_kg", "weight"))
        weight_kg: float | None = None
        if not is_missing_value(raw_weight):
            try:
                w = float(raw_weight)
                w_unit = _extract_col(brow, ("weight_unit",))
                if not is_missing_value(w_unit) and str(w_unit).strip().lower() in {"lb", "lbs"}:
                    weight_kg = round(w * 0.45359237, 1)
                else:
                    weight_kg = round(w, 1)
            except (TypeError, ValueError):
                pass

        raw_height = _extract_col(brow, ("height", "height_cm"))
        height_cm: float | None = None
        if not is_missing_value(raw_height):
            try:
                h = float(raw_height)
                h_unit = _extract_col(brow, ("height_unit",))
                if not is_missing_value(h_unit) and str(h_unit).strip().lower() in {"in", "inch", "inches"}:
                    height_cm = round(h * 2.54, 1)
                else:
                    height_cm = round(h, 1)
            except (TypeError, ValueError):
                pass

        patient = db.scalar(
            select(Patient).where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == DATASET_NAME,
                Patient.external_id == ext_id,
            )
        )
        if patient is None:
            patient = Patient(
                user_id=None,
                dataset_import_id=dataset_import.id,
                cohort_type="research_participant",
                external_id=ext_id,
                display_name=f"Research Participant {ext_id}",
                age=age_val,
                sex=sex_val,
                diabetes_type=diabetes_type,
                height_cm=height_cm,
                weight_kg=weight_kg,
                consent_granted=bool(participant_consent_version),
                consent_version=participant_consent_version,
                retention_policy="dataset_license_bound",
                source_dataset=DATASET_NAME,
            )
            db.add(patient)
            db.flush()
        participants_ingested += 1

        raw_rows = _load_tabular(ts_source)
        parsed_rows: list[tuple[int, datetime, str, str, dict[str, Any]]] = []
        for idx, row in enumerate(raw_rows):
            rec_id = f"{ext_id}:row_{idx}"
            raw_ts = _extract_col(row, ("timestamp", "date", "recorded_at", "time"))
            try:
                ts_utc, raw_ts_str, _, tz_basis = parse_timestamp_with_semantics(
                    raw_ts, semantics="date_shifted_relative"
                )
            except ValueError as err:
                tracker.reject(source_record_id=rec_id, reason=str(err), raw_payload=row)
                continue
            parsed_rows.append((idx, ts_utc, raw_ts_str, tz_basis, row))

        parsed_rows.sort(key=lambda item: (item[1], item[0]))

        if brow and parsed_rows:
            first_ts = parsed_rows[0][1]
            bmi_raw = _extract_col(brow, ("bmi",))
            fpg_raw = _extract_col(brow, ("fasting glu - pdl (lab)", "fasting_glucose_mg_dl"))
            db.add(
                ClinicalRecord(
                    patient_id=patient.id,
                    cohort_type="research_participant",
                    dataset_import_id=dataset_import.id,
                    recorded_at=first_ts,
                    hba1c_pct=hba1c_val,
                    bmi=float(bmi_raw) if not is_missing_value(bmi_raw) else None,
                    fasting_glucose_mg_dl=float(fpg_raw) if not is_missing_value(fpg_raw) else None,
                    source_dataset=DATASET_NAME,
                    source_record_id=f"{ext_id}:bio_summary",
                )
            )
            tracker.accept()

        existing_glucose_keys: set[tuple[datetime, str, str]] = set(
            (r_ts, r_type, r_dev or "__none__")
            for r_ts, r_type, r_dev in db.execute(
                select(
                    GlucoseReading.recorded_at,
                    GlucoseReading.reading_type,
                    GlucoseReading.device_id,
                ).where(GlucoseReading.patient_id == patient.id)
            ).all()
        )

        for idx, ts_utc, raw_ts_str, tz_basis, row in parsed_rows:
            rec_id = f"{ext_id}:row_{idx}"
            raw_unit_col = _extract_col(row, ("unit", "raw_unit"))
            unit_str = str(raw_unit_col).strip() if not is_missing_value(raw_unit_col) else "mg/dL"

            # 1. Libre GL (FreeStyle Libre Pro, nominal 15-min sensor)
            libre_raw = _extract_col(row, ("libre gl", "libre_gl", "freestyle_libre"))
            if not is_missing_value(libre_raw):
                try:
                    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(libre_raw, unit_str)
                    g_key = (ts_utc, "cgm", LIBRE_PRO_DEVICE)
                    if g_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:libre",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(g_key)
                        prov = _resolve_row_provenance(
                            row,
                            device_candidates=("libre provenance", "libre_provenance"),
                            source_verified_native_export=source_verified_native_export,
                        )
                        provenance_counts[prov] = provenance_counts.get(prov, 0) + 1
                        db.add(
                            GlucoseReading(
                                patient_id=patient.id,
                                cohort_type="research_participant",
                                dataset_import_id=dataset_import.id,
                                recorded_at=ts_utc,
                                raw_timestamp=raw_ts_str,
                                timestamp_semantics="date_shifted_relative",
                                timezone_basis=tz_basis,
                                glucose_mg_dl=g_mg_dl,
                                raw_value=g_raw,
                                raw_unit=g_unit,
                                reading_type="cgm",
                                device_id=LIBRE_PRO_DEVICE,
                                sampling_interval_min=LIBRE_SAMPLING_MIN,
                                observation_provenance=prov,
                                source_dataset=DATASET_NAME,
                                source_record_id=f"{rec_id}:libre",
                            )
                        )
                        tracker.accept()
                except ValueError as err:
                    tracker.reject(
                        source_record_id=f"{rec_id}:libre",
                        reason=str(err),
                        raw_payload=row,
                    )

            # 2. Dexcom GL (Dexcom G6 Pro, nominal 5-min sensor)
            dexcom_raw = _extract_col(row, ("dexcom gl", "dexcom_gl", "dexcom"))
            if not is_missing_value(dexcom_raw):
                try:
                    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(dexcom_raw, unit_str)
                    g_key = (ts_utc, "cgm", DEXCOM_G6_PRO_DEVICE)
                    if g_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:dexcom",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(g_key)
                        prov = _resolve_row_provenance(
                            row,
                            device_candidates=("dexcom provenance", "dexcom_provenance"),
                            source_verified_native_export=source_verified_native_export,
                        )
                        provenance_counts[prov] = provenance_counts.get(prov, 0) + 1
                        db.add(
                            GlucoseReading(
                                patient_id=patient.id,
                                cohort_type="research_participant",
                                dataset_import_id=dataset_import.id,
                                recorded_at=ts_utc,
                                raw_timestamp=raw_ts_str,
                                timestamp_semantics="date_shifted_relative",
                                timezone_basis=tz_basis,
                                glucose_mg_dl=g_mg_dl,
                                raw_value=g_raw,
                                raw_unit=g_unit,
                                reading_type="cgm",
                                device_id=DEXCOM_G6_PRO_DEVICE,
                                sampling_interval_min=DEXCOM_SAMPLING_MIN,
                                observation_provenance=prov,
                                source_dataset=DATASET_NAME,
                                source_record_id=f"{rec_id}:dexcom",
                            )
                        )
                        tracker.accept()
                except ValueError as err:
                    tracker.reject(
                        source_record_id=f"{rec_id}:dexcom",
                        reason=str(err),
                        raw_payload=row,
                    )

            # 3. Meal log
            meal_type_raw = _extract_col(row, ("meal type", "meal_type"))
            carbs_raw = _extract_col(row, ("carbs", "carbs_g"))
            cals_raw = _extract_col(row, ("calories", "kcal"))
            if not is_missing_value(meal_type_raw) or not is_missing_value(carbs_raw):
                m_type = _normalize_meal_type(meal_type_raw)
                prot_raw = _extract_col(row, ("protein", "protein_g"))
                fat_raw = _extract_col(row, ("fat", "fat_g"))
                fiber_raw = _extract_col(row, ("fiber", "fiber_g"))
                img_raw = _extract_col(row, ("image path", "photo_ref"))

                def _opt_float(val: Any) -> float | None:
                    if is_missing_value(val):
                        return None
                    try:
                        return round(float(val), 2)
                    except (TypeError, ValueError):
                        return None

                db.add(
                    Meal(
                        patient_id=patient.id,
                        cohort_type="research_participant",
                        dataset_import_id=dataset_import.id,
                        logged_at=ts_utc,
                        raw_timestamp=raw_ts_str,
                        timestamp_semantics="date_shifted_relative",
                        timezone_basis=tz_basis,
                        meal_type=m_type,
                        description=f"CGMacros {m_type} log",
                        ingredients=[],
                        calories=_opt_float(cals_raw),
                        carbs_g=_opt_float(carbs_raw),
                        protein_g=_opt_float(prot_raw),
                        fat_g=_opt_float(fat_raw),
                        fiber_g=_opt_float(fiber_raw),
                        photo_ref=str(img_raw).strip()[:255] if not is_missing_value(img_raw) else None,
                        source_dataset=DATASET_NAME,
                        source_record_id=f"{rec_id}:meal",
                    )
                )
                tracker.accept()

            # 4. Activity log
            hr_raw = _extract_col(row, ("hr", "heart_rate_bpm"))
            steps_raw = _extract_col(row, ("steps",))
            if not is_missing_value(hr_raw) or not is_missing_value(steps_raw):
                try:
                    hr_val = float(hr_raw) if not is_missing_value(hr_raw) else None
                    steps_val = int(float(steps_raw)) if not is_missing_value(steps_raw) else None
                    db.add(
                        ActivityRecord(
                            patient_id=patient.id,
                            cohort_type="research_participant",
                            recorded_at=ts_utc,
                            steps=steps_val,
                            heart_rate_bpm=hr_val,
                            intensity="unknown",
                            source_dataset=DATASET_NAME,
                            source_record_id=f"{rec_id}:activity",
                        )
                    )
                    tracker.accept()
                except (TypeError, ValueError):
                    pass

    dataset_import.status = "completed"
    dataset_import.records_accepted = tracker.accepted_count
    dataset_import.records_rejected = tracker.rejected_count
    dataset_import.completed_at = datetime.now(timezone.utc)
    dataset_import.quality_report_summary = tracker.to_quality_report(
        extra={
            "participants_ingested": participants_ingested,
            "excluded_non_t2d_participants": excluded_non_t2d,
            "t2d_only": t2d_only,
            "dataset_doi": dataset_doi,
            "source_url": source_url,
            "license_identifier": LICENSE_IDENTIFIER,
            "license_url": LICENSE_URL,
            "timestamp_semantics": "date_shifted_relative",
            "timezone_basis": "not_applicable_relative",
            "source_verified_native_export": source_verified_native_export,
            "native_evidence_reference": cleaned_evidence_ref,
            "observation_provenance_counts": provenance_counts,
        }
    )
    record_audit_event(
        db,
        action="create_log",
        resource_type="dataset_import",
        resource_id=str(dataset_import.id),
        context_metadata={
            "dataset_name": DATASET_NAME,
            "dataset_version": dataset_version,
            "dataset_doi": dataset_doi,
            "source_verified_native_export": source_verified_native_export,
            "native_evidence_reference": cleaned_evidence_ref,
        },
    )
    db.commit()

    return IngestionSummary(
        dataset_import_id=str(dataset_import.id),
        dataset_name=DATASET_NAME,
        dataset_version=dataset_version,
        dataset_doi=dataset_doi,
        source_url=source_url,
        license_identifier=LICENSE_IDENTIFIER,
        license_url=LICENSE_URL,
        preprocessing_version=preprocessing_version,
        source_file_checksum=source_file_checksum,
        directory_manifest_checksum=directory_manifest_checksum,
        input_payload_checksum=input_payload_checksum,
        records_accepted=tracker.accepted_count,
        records_rejected=tracker.rejected_count,
        rejection_reasons=dict(tracker.reasons),
        rejected_samples=list(tracker.samples),
        participants_ingested=participants_ingested,
        excluded_non_t2d_participants=excluded_non_t2d,
        observation_provenance_counts=provenance_counts,
        timestamp_semantics="date_shifted_relative",
        timezone_basis="not_applicable_relative",
    )
