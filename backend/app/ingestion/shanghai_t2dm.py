from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.common import (
    PREPROCESSING_VERSION,
    SHANGHAI_TZ,
    IngestionSummary,
    RejectionTracker,
    compute_sha256,
    is_missing_value,
    normalize_glucose_reading,
    parse_utc_timestamp,
)
from app.models import (
    ClinicalRecord,
    DatasetImport,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
)

DATASET_NAME = "shanghai_t2dm"
DEFAULT_DATASET_VERSION = "figshare-v1-2023"
FREESTYLE_LIBRE_H_DEVICE = "FreeStyle_Libre_H"
SHANGHAI_CGM_INTERVAL_MIN = 15


def _load_tabular(source: Path | pd.DataFrame | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(source, list):
        return source
    if isinstance(source, pd.DataFrame):
        return source.to_dict(orient="records")
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    elif suffix == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported ShanghaiT2DM file format: {suffix}")
    return df.to_dict(orient="records")


def _normalize_sex(raw_sex: Any) -> str | None:
    if is_missing_value(raw_sex):
        return None
    s = str(raw_sex).strip().lower()
    if s in {"f", "female", "2", "woman"}:
        return "female"
    if s in {"m", "male", "1", "man"}:
        return "male"
    return s[:32]


def _extract_column(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    lower_map = {str(k).strip().lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def ingest_shanghai_t2dm(
    db: Session,
    *,
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    summary_source: Path | pd.DataFrame | list[dict[str, Any]] | None = None,
    source_checksum_target: Path | str | bytes | None = None,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    preprocessing_version: str = PREPROCESSING_VERSION,
    default_tz: timezone = SHANGHAI_TZ,
) -> IngestionSummary:
    """Ingest ShanghaiT2DM research participant data with strict provenance & validation.

    Non-negotiable rules enforced:
    - Cohort is strictly ``research_participant`` with ``diabetes_type = 'T2D'``.
    - Native FreeStyle Libre H sampling interval (``15`` min) and device_id are preserved.
    - Medication columns are stored as prescribed regimens or ``status='unknown'`` clinical
      record events — never fabricated as ``taken`` or ``missed`` adherence.
    - Duplicate timestamps for the same (patient_id, recorded_at, reading_type) are rejected
      and logged rather than silently overwriting existing observations.
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

    summary_by_ext_id: dict[str, dict[str, Any]] = {}
    if summary_source is not None:
        for srow in _load_tabular(summary_source):
            raw_pid = _extract_column(
                srow, ("patient number", "patient_id", "subject_id", "id")
            )
            if not is_missing_value(raw_pid):
                ext_key = str(raw_pid).strip()
                summary_by_ext_id[ext_key] = srow
                base_id = ext_key.split("_")[0]
                summary_by_ext_id.setdefault(base_id, srow)

    participants_ingested = 0

    for ext_id, ts_source in participant_sources.items():
        clean_ext_id = str(ext_id).strip()
        base_ext_id = clean_ext_id.split("_")[0]
        srow = summary_by_ext_id.get(clean_ext_id) or summary_by_ext_id.get(base_ext_id) or {}

        # Check explicitly if summary row mistakenly marks T1D
        declared_type = _extract_column(srow, ("diabetes_type", "type"))
        if not is_missing_value(declared_type) and str(declared_type).strip().upper() == "T1D":
            tracker.reject(
                source_record_id=f"{clean_ext_id}:summary",
                reason="t1d_cohort_mixing_forbidden",
                raw_payload={"external_id": clean_ext_id, "diabetes_type": declared_type},
            )
            continue

        raw_age = _extract_column(srow, ("age (years)", "age"))
        age_val: int | None = None
        if not is_missing_value(raw_age):
            try:
                parsed_age = int(float(raw_age))
                if 1 <= parsed_age <= 120:
                    age_val = parsed_age
            except (TypeError, ValueError):
                pass

        raw_height = _extract_column(srow, ("height (m)", "height (cm)", "height"))
        height_cm: float | None = None
        if not is_missing_value(raw_height):
            try:
                h_val = float(raw_height)
                height_cm = round(h_val * 100.0, 1) if h_val < 3.0 else round(h_val, 1)
            except (TypeError, ValueError):
                pass

        raw_weight = _extract_column(srow, ("weight (kg)", "weight"))
        weight_kg: float | None = None
        if not is_missing_value(raw_weight):
            try:
                weight_kg = round(float(raw_weight), 1)
            except (TypeError, ValueError):
                pass

        patient = db.scalar(
            select(Patient).where(
                Patient.cohort_type == "research_participant",
                Patient.source_dataset == DATASET_NAME,
                Patient.external_id == base_ext_id,
            )
        )
        if patient is None:
            patient = Patient(
                user_id=None,
                dataset_import_id=dataset_import.id,
                cohort_type="research_participant",
                external_id=base_ext_id,
                display_name=f"Research Participant ST2D-{base_ext_id}",
                age=age_val,
                sex=_normalize_sex(_extract_column(srow, ("gender", "sex"))),
                diabetes_type="T2D",
                height_cm=height_cm,
                weight_kg=weight_kg,
                consent_granted=True,
                consent_version="figshare-cc-by-4.0",
                retention_policy="dataset_license_bound",
                source_dataset=DATASET_NAME,
            )
            db.add(patient)
            db.flush()
        participants_ingested += 1

        # Load and parse time-series rows
        raw_rows = _load_tabular(ts_source)
        parsed_rows: list[tuple[int, datetime, dict[str, Any]]] = []
        for idx, row in enumerate(raw_rows):
            rec_id = f"{clean_ext_id}:row_{idx}"
            raw_ts = _extract_column(row, ("date", "timestamp", "recorded_at", "time"))
            try:
                ts_utc = parse_utc_timestamp(raw_ts, default_tz=default_tz)
            except ValueError as err:
                tracker.reject(source_record_id=rec_id, reason=str(err), raw_payload=row)
                continue
            parsed_rows.append((idx, ts_utc, row))

        # Sort chronologically to handle out-of-order source rows deterministically
        parsed_rows.sort(key=lambda item: (item[1], item[0]))

        # Optional baseline clinical record if summary labs exist
        if srow and parsed_rows:
            first_ts = parsed_rows[0][1]
            hba1c = _extract_column(srow, ("hba1c (%)", "hba1c", "a1c"))
            bmi = _extract_column(srow, ("bmi (kg/m2)", "bmi"))
            fpg = _extract_column(
                srow, ("fasting plasma glucose (mg/dl)", "fasting glucose", "fpg")
            )
            clin = ClinicalRecord(
                patient_id=patient.id,
                cohort_type="research_participant",
                dataset_import_id=dataset_import.id,
                recorded_at=first_ts,
                hba1c_pct=float(hba1c) if not is_missing_value(hba1c) else None,
                bmi=float(bmi) if not is_missing_value(bmi) else None,
                fasting_glucose_mg_dl=float(fpg) if not is_missing_value(fpg) else None,
                source_dataset=DATASET_NAME,
                source_record_id=f"{clean_ext_id}:clinical_summary",
            )
            db.add(clin)
            tracker.accept()

        existing_glucose_keys: set[tuple[datetime, str]] = set(
            db.execute(
                select(GlucoseReading.recorded_at, GlucoseReading.reading_type).where(
                    GlucoseReading.patient_id == patient.id
                )
            ).all()
        )
        known_meds: dict[str, Medication] = {}

        for idx, ts_utc, row in parsed_rows:
            rec_id = f"{clean_ext_id}:row_{idx}"
            raw_unit_col = _extract_column(row, ("unit", "raw_unit", "glucose_unit"))
            unit_str = str(raw_unit_col).strip() if not is_missing_value(raw_unit_col) else "mg/dL"

            # 1. CGM reading
            cgm_raw = _extract_column(
                row, ("cgm (mg / dl)", "cgm (mg/dl)", "cgm", "glucose_cgm", "cgm (mmol / l)")
            )
            if not is_missing_value(cgm_raw):
                inferred_unit = (
                    "mmol/L"
                    if any("mmol" in str(k).lower() for k in row.keys() if "cgm" in str(k).lower())
                    and is_missing_value(raw_unit_col)
                    else unit_str
                )
                try:
                    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(cgm_raw, inferred_unit)
                    g_key = (ts_utc, "cgm")
                    if g_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cgm",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(g_key)
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
                                device_id=FREESTYLE_LIBRE_H_DEVICE,
                                sampling_interval_min=SHANGHAI_CGM_INTERVAL_MIN,
                                source_dataset=DATASET_NAME,
                                source_record_id=f"{rec_id}:cgm",
                            )
                        )
                        tracker.accept()
                except ValueError as err:
                    tracker.reject(
                        source_record_id=f"{rec_id}:cgm",
                        reason=str(err),
                        raw_payload=row,
                    )

            # 2. CBG fingerstick reading
            cbg_raw = _extract_column(row, ("cbg (mg / dl)", "cbg (mg/dl)", "cbg"))
            if not is_missing_value(cbg_raw):
                try:
                    c_mg_dl, c_raw, c_unit = normalize_glucose_reading(cbg_raw, unit_str)
                    c_key = (ts_utc, "cbg")
                    if c_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cbg",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(c_key)
                        db.add(
                            GlucoseReading(
                                patient_id=patient.id,
                                cohort_type="research_participant",
                                dataset_import_id=dataset_import.id,
                                recorded_at=ts_utc,
                                glucose_mg_dl=c_mg_dl,
                                raw_value=c_raw,
                                raw_unit=c_unit,
                                reading_type="cbg",
                                device_id=None,
                                sampling_interval_min=None,
                                source_dataset=DATASET_NAME,
                                source_record_id=f"{rec_id}:cbg",
                            )
                        )
                        tracker.accept()
                except ValueError as err:
                    tracker.reject(
                        source_record_id=f"{rec_id}:cbg",
                        reason=str(err),
                        raw_payload=row,
                    )

            # 3. Dietary intake -> Meal (never fabricate macros if absent)
            diet_raw = _extract_column(row, ("dietary intake", "meal", "diet"))
            if not is_missing_value(diet_raw):
                carbs_raw = _extract_column(row, ("carbs", "carbs_g", "carbohydrate (g)"))
                carbs_val: float | None = None
                if not is_missing_value(carbs_raw):
                    try:
                        carbs_val = float(carbs_raw)
                    except (TypeError, ValueError):
                        pass
                db.add(
                    Meal(
                        patient_id=patient.id,
                        cohort_type="research_participant",
                        dataset_import_id=dataset_import.id,
                        logged_at=ts_utc,
                        meal_type="unknown",
                        description=str(diet_raw).strip(),
                        ingredients=[],
                        carbs_g=carbs_val,
                        source_dataset=DATASET_NAME,
                        source_record_id=f"{rec_id}:meal",
                    )
                )
                tracker.accept()

            # 4. Medication notations -> Medication + MedicationEvent(status='unknown', event_source='clinical_record')
            for med_col_candidates, drug_class in (
                (
                    ("non-insulin hypoglycemic agents", "oral hypoglycemic agents"),
                    "non_insulin_hypoglycemic",
                ),
                (
                    ("insulin dose - s.c.", "insulin dose - i.v.", "insulin dose"),
                    "insulin",
                ),
            ):
                med_text = _extract_column(row, med_col_candidates)
                if not is_missing_value(med_text):
                    med_str = str(med_text).strip()
                    med_obj = known_meds.get(med_str)
                    if med_obj is None:
                        med_obj = Medication(
                            patient_id=patient.id,
                            cohort_type="research_participant",
                            dataset_import_id=dataset_import.id,
                            medication_name=med_str[:255],
                            drug_class=drug_class,
                            recorded_dose=med_str[:128],
                            is_active=True,
                            source_dataset=DATASET_NAME,
                            source_record_id=f"{rec_id}:med_regimen",
                        )
                        db.add(med_obj)
                        db.flush()
                        known_meds[med_str] = med_obj

                    db.add(
                        MedicationEvent(
                            patient_id=patient.id,
                            cohort_type="research_participant",
                            medication_id=med_obj.id,
                            event_time=ts_utc,
                            status="unknown",
                            event_source="clinical_record",
                            notes=med_str,
                            source_dataset=DATASET_NAME,
                            source_record_id=f"{rec_id}:med_event",
                        )
                    )
                    tracker.accept()

    dataset_import.status = "completed"
    dataset_import.records_accepted = tracker.accepted_count
    dataset_import.records_rejected = tracker.rejected_count
    dataset_import.completed_at = datetime.now(timezone.utc)
    dataset_import.quality_report_summary = tracker.to_quality_report(
        extra={
            "participants_ingested": participants_ingested,
            "native_cgm_device": FREESTYLE_LIBRE_H_DEVICE,
            "native_sampling_interval_min": SHANGHAI_CGM_INTERVAL_MIN,
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
    )
