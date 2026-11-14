from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.common import (
    PREPROCESSING_VERSION,
    IngestionSummary,
    RejectionTracker,
    compute_sha256,
    is_missing_value,
    normalize_glucose_reading,
    parse_utc_timestamp,
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
DEFAULT_DATASET_VERSION = "physionet-v1.0.0"
LIBRE_PRO_DEVICE = "FreeStyle_Libre_Pro"
DEXCOM_G6_PRO_DEVICE = "Dexcom_G6_Pro"
LIBRE_SAMPLING_MIN = 15
DEXCOM_SAMPLING_MIN = 5


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


def ingest_cgmacros(
    db: Session,
    *,
    bio_source: Path | pd.DataFrame | list[dict[str, Any]],
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    source_checksum_target: Path | str | bytes | None = None,
    t2d_only: bool = True,
    preserve_native_cadence: bool = True,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    preprocessing_version: str = PREPROCESSING_VERSION,
) -> IngestionSummary:
    """Ingest CGMacros dataset with strict T2D separation and native CGM cadence preservation.

    Non-negotiable rules enforced:
    - Classifies participants via ``bio.csv`` HbA1c (``A1c PDL (Lab) > 6.4%`` => ``T2D``).
    - When ``t2d_only=True`` (default for T2D analysis), excludes non-T2D participants
      (``prediabetes`` and ``healthy``) so cohorts are never mixed.
    - Rejects any ``T1D`` rows (``t1d_cohort_mixing_forbidden``).
    - Preserves dual-CGM provenance: ``FreeStyle_Libre_Pro`` (``15`` min) and
      ``Dexcom_G6_Pro`` (``5`` min). When ``preserve_native_cadence=True``, down-samples
      1-minute interpolated CSV grids back to native sensor sampling intervals.
    """
    tracker = RejectionTracker()
    checksum = compute_sha256(
        source_checksum_target
        if source_checksum_target is not None
        else str(sorted(participant_sources.keys())).encode("utf-8")
    )

    dataset_import = DatasetImport(
        dataset_name=DATASET_NAME,
        dataset_version=dataset_version,
        source_file_checksum=checksum,
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
                # CGMacros bio.csv often reports body weight in lbs (~110-300 lbs); convert if weight_unit='lbs'
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
                consent_granted=True,
                consent_version="physionet-cc-by-4.0",
                retention_policy="dataset_license_bound",
                source_dataset=DATASET_NAME,
            )
            db.add(patient)
            db.flush()
        participants_ingested += 1

        raw_rows = _load_tabular(ts_source)
        parsed_rows: list[tuple[int, datetime, dict[str, Any]]] = []
        for idx, row in enumerate(raw_rows):
            rec_id = f"{ext_id}:row_{idx}"
            raw_ts = _extract_col(row, ("timestamp", "date", "recorded_at", "time"))
            try:
                ts_utc = parse_utc_timestamp(raw_ts, default_tz=timezone.utc)
            except ValueError as err:
                tracker.reject(source_record_id=rec_id, reason=str(err), raw_payload=row)
                continue
            parsed_rows.append((idx, ts_utc, row))

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

        existing_glucose_keys: set[tuple[datetime, str]] = set(
            db.execute(
                select(GlucoseReading.recorded_at, GlucoseReading.device_id).where(
                    GlucoseReading.patient_id == patient.id
                )
            ).all()
        )

        last_libre_ts: datetime | None = None
        last_dexcom_ts: datetime | None = None

        for idx, ts_utc, row in parsed_rows:
            rec_id = f"{ext_id}:row_{idx}"
            raw_unit_col = _extract_col(row, ("unit", "raw_unit"))
            unit_str = str(raw_unit_col).strip() if not is_missing_value(raw_unit_col) else "mg/dL"

            # 1. Libre GL (FreeStyle Libre Pro, native 15-min interval)
            libre_raw = _extract_col(row, ("libre gl", "libre_gl", "freestyle_libre"))
            if not is_missing_value(libre_raw):
                elapsed_ok = (
                    not preserve_native_cadence
                    or last_libre_ts is None
                    or ts_utc == last_libre_ts
                    or (ts_utc - last_libre_ts).total_seconds() >= LIBRE_SAMPLING_MIN * 60 - 1e-6
                )
                if elapsed_ok:
                    try:
                        g_mg_dl, g_raw, g_unit = normalize_glucose_reading(libre_raw, unit_str)
                        g_key = (ts_utc, LIBRE_PRO_DEVICE)
                        if g_key in existing_glucose_keys:
                            tracker.reject(
                                source_record_id=f"{rec_id}:libre",
                                reason="duplicate_timestamp",
                                raw_payload=row,
                            )
                        else:
                            existing_glucose_keys.add(g_key)
                            last_libre_ts = ts_utc
                            db.add(
                                GlucoseReading(
                                    patient_id=patient.id,
                                    cohort_type="research_participant",
                                    dataset_import_id=dataset_import.id,
                                    recorded_at=ts_utc,
                                    glucose_mg_dl=g_mg_dl,
                                    raw_value=g_raw,
                                    raw_unit=g_unit,
                                    reading_type="cgm",
                                    device_id=LIBRE_PRO_DEVICE,
                                    sampling_interval_min=LIBRE_SAMPLING_MIN,
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

            # 2. Dexcom GL (Dexcom G6 Pro, native 5-min interval)
            dexcom_raw = _extract_col(row, ("dexcom gl", "dexcom_gl", "dexcom"))
            if not is_missing_value(dexcom_raw):
                elapsed_ok = (
                    not preserve_native_cadence
                    or last_dexcom_ts is None
                    or ts_utc == last_dexcom_ts
                    or (ts_utc - last_dexcom_ts).total_seconds() >= DEXCOM_SAMPLING_MIN * 60 - 1e-6
                )
                if elapsed_ok:
                    try:
                        g_mg_dl, g_raw, g_unit = normalize_glucose_reading(dexcom_raw, unit_str)
                        g_key = (ts_utc, DEXCOM_G6_PRO_DEVICE)
                        if g_key in existing_glucose_keys:
                            tracker.reject(
                                source_record_id=f"{rec_id}:dexcom",
                                reason="duplicate_timestamp",
                                raw_payload=row,
                            )
                        else:
                            existing_glucose_keys.add(g_key)
                            last_dexcom_ts = ts_utc
                            db.add(
                                GlucoseReading(
                                    patient_id=patient.id,
                                    cohort_type="research_participant",
                                    dataset_import_id=dataset_import.id,
                                    recorded_at=ts_utc,
                                    glucose_mg_dl=g_mg_dl,
                                    raw_value=g_raw,
                                    raw_unit=g_unit,
                                    reading_type="cgm",
                                    device_id=DEXCOM_G6_PRO_DEVICE,
                                    sampling_interval_min=DEXCOM_SAMPLING_MIN,
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

            # 3. Meal log (when Meal Type or Carbs/Calories logged on this timestamp)
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

            # 4. Activity log (HR / Steps when present; only log at 15-min cadence if preserve_native_cadence)
            hr_raw = _extract_col(row, ("hr", "heart_rate_bpm"))
            steps_raw = _extract_col(row, ("steps",))
            if not is_missing_value(hr_raw) or not is_missing_value(steps_raw):
                if not preserve_native_cadence or ts_utc.minute % 15 == 0:
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
            "preserve_native_cadence": preserve_native_cadence,
        }
    )
    db.commit()

    return IngestionSummary(
        dataset_import_id=str(dataset_import.id),
        dataset_name=DATASET_NAME,
        dataset_version=dataset_version,
        preprocessing_version=preprocessing_version,
        source_file_checksum=checksum,
        records_accepted=tracker.accepted_count,
        records_rejected=tracker.rejected_count,
        rejection_reasons=dict(tracker.reasons),
        rejected_samples=list(tracker.samples),
        participants_ingested=participants_ingested,
        excluded_non_t2d_participants=excluded_non_t2d,
    )
