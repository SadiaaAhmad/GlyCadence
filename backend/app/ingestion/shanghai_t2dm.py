from datetime import datetime, timedelta, timezone
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
    ClinicalRecord,
    DatasetImport,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
)

DATASET_NAME = "shanghai_t2dm"
DEFAULT_DATASET_VERSION = "figshare-item-20444397-v1"
DEFAULT_DATASET_DOI = "10.6084/m9.figshare.20444397.v1"
DEFAULT_COLLECTION_DOI = "10.6084/m9.figshare.c.6310860.v1"
DEFAULT_SOURCE_URL = "https://ndownloader.figshare.com/files/36582306"
LICENSE_IDENTIFIER = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
FREESTYLE_LIBRE_H_DEVICE = "FreeStyle_Libre_H"
SHANGHAI_CGM_INTERVAL_MIN = 15
VALID_PROVENANCES: set[str] = {"native", "interpolated", "derived", "unknown"}


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


def _resolve_checksums(
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    summary_source: Path | pd.DataFrame | list[dict[str, Any]] | None,
    source_file_path: Path | str | None,
) -> tuple[str | None, str | None, str]:
    """Compute (source_file_checksum, directory_manifest_checksum, input_payload_checksum)."""
    file_checksum: str | None = None
    dir_checksum: str | None = None
    if source_file_path is not None:
        file_checksum, dir_checksum = resolve_source_checksums(source_file_path)
    else:
        all_paths = [
            Path(v)
            for v in participant_sources.values()
            if isinstance(v, (Path, str)) and Path(v).exists()
        ]
        if len(all_paths) == len(participant_sources) and len(all_paths) > 0:
            if len(all_paths) == 1 and all_paths[0].is_file():
                file_checksum, dir_checksum = resolve_source_checksums(all_paths[0])
            else:
                parent_dirs = {p.parent for p in all_paths}
                if len(parent_dirs) == 1:
                    file_checksum, dir_checksum = resolve_source_checksums(next(iter(parent_dirs)))

    canonical_payload = {
        "dataset_name": DATASET_NAME,
        "participants": {
            str(k): (_load_tabular(v) if not isinstance(v, list) else v)
            for k, v in sorted(participant_sources.items(), key=lambda item: str(item[0]))
        },
        "summary": (_load_tabular(summary_source) if summary_source is not None else None),
    }
    payload_checksum = compute_input_payload_checksum(canonical_payload)
    return file_checksum, dir_checksum, payload_checksum


def _resolve_row_provenance(
    row: dict[str, Any],
    *,
    source_verified_native_export: bool,
) -> ObservationProvenanceType:
    explicit = _extract_column(row, ("observation_provenance", "cgm_provenance", "provenance"))
    if not is_missing_value(explicit):
        cleaned = str(explicit).strip().lower()
        if cleaned in VALID_PROVENANCES:
            return cleaned  # type: ignore[return-value]
    return "native" if source_verified_native_export else "unknown"


def ingest_shanghai_t2dm(
    db: Session,
    *,
    participant_sources: dict[str, Path | pd.DataFrame | list[dict[str, Any]]],
    summary_source: Path | pd.DataFrame | list[dict[str, Any]] | None = None,
    source_file_path: Path | str | None = None,
    dataset_version: str = DEFAULT_DATASET_VERSION,
    dataset_doi: str = DEFAULT_DATASET_DOI,
    source_url: str = DEFAULT_SOURCE_URL,
    preprocessing_version: str = PREPROCESSING_VERSION,
    assumed_iana_tz: str | None = "Asia/Shanghai",
    source_verified_native_export: bool = False,
    native_evidence_reference: str | None = None,
    participant_consent_version: str | None = None,
) -> IngestionSummary:
    """Ingest ShanghaiT2DM research participant data with strict provenance & validation.

    Non-negotiable rules enforced:
    - Figshare item/version (``10.6084/m9.figshare.20444397.v1`` in collection ``6310860``)
      and license ``CC BY 4.0`` recorded on ``DatasetImport`` — never stored in ``Patient.consent_version``.
    - ``source_verified_native_export`` defaults to ``False`` (all unverified rows default to ``'unknown'``).
      Setting ``source_verified_native_export=True`` requires a non-empty ``native_evidence_reference``
      citation, which is recorded in ``dataset_imports.quality_report_summary`` and ``audit_logs``.
    - CBG / finger-stick rows are never stamped as ``native`` CGM.
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
        participant_sources, summary_source, source_file_path
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
    provenance_counts: dict[str, int] = {"native": 0, "interpolated": 0, "derived": 0, "unknown": 0}
    observed_timezone_bases: set[str] = set()

    for ext_id, ts_source in participant_sources.items():
        clean_ext_id = str(ext_id).strip()
        base_ext_id = clean_ext_id.split("_")[0]
        srow = summary_by_ext_id.get(clean_ext_id) or summary_by_ext_id.get(base_ext_id) or {}

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
                consent_granted=bool(participant_consent_version),
                consent_version=participant_consent_version,
                retention_policy="dataset_license_bound",
                source_dataset=DATASET_NAME,
            )
            db.add(patient)
            db.flush()
        participants_ingested += 1

        known_meds: dict[str, Medication] = {}

        # Static medication regimen descriptions in summary sheet create Medication rows ONLY (never MedicationEvents)
        for sum_med_cols, sum_drug_class in (
            (
                ("hypoglycemic agents", "non-insulin hypoglycemic agents", "oral hypoglycemic agents"),
                "non_insulin_hypoglycemic",
            ),
            (("insulin", "insulin regimen"), "insulin"),
        ):
            sum_med_raw = _extract_column(srow, sum_med_cols)
            if not is_missing_value(sum_med_raw):
                sum_med_str = str(sum_med_raw).strip()
                if sum_med_str.lower() not in {"none", "no", "0"}:
                    if sum_med_str not in known_meds:
                        med_obj = Medication(
                            patient_id=patient.id,
                            cohort_type="research_participant",
                            dataset_import_id=dataset_import.id,
                            medication_name=sum_med_str[:255],
                            drug_class=sum_drug_class,
                            recorded_dose=sum_med_str[:128],
                            is_active=True,
                            source_dataset=DATASET_NAME,
                            source_record_id=f"{clean_ext_id}:summary_med:{sum_drug_class}",
                        )
                        db.add(med_obj)
                        db.flush()
                        known_meds[sum_med_str] = med_obj
                        tracker.accept()

        raw_rows = _load_tabular(ts_source)
        parsed_rows: list[tuple[int, datetime, str, str, dict[str, Any]]] = []
        for idx, row in enumerate(raw_rows):
            rec_id = f"{clean_ext_id}:row_{idx}"
            raw_ts = _extract_column(row, ("date", "timestamp", "recorded_at", "time"))
            try:
                ts_utc, raw_ts_str, _, tz_basis = parse_timestamp_with_semantics(
                    raw_ts,
                    semantics="real_world_local",
                    assumed_iana_tz=assumed_iana_tz,
                )
            except ValueError as err:
                tracker.reject(source_record_id=rec_id, reason=str(err), raw_payload=row)
                continue
            observed_timezone_bases.add(tz_basis)
            parsed_rows.append((idx, ts_utc, raw_ts_str, tz_basis, row))

        parsed_rows.sort(key=lambda item: (item[1], item[0]))

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

        # Track contiguous fill-down state per drug_class: (med_str, last_ts_utc, sheet_name)
        last_contiguous_med_by_class: dict[str, tuple[str, datetime, str] | None] = {}

        for idx, ts_utc, raw_ts_str, tz_basis, row in parsed_rows:
            rec_id = f"{clean_ext_id}:row_{idx}"
            raw_unit_col = _extract_column(row, ("unit", "raw_unit", "glucose_unit"))
            unit_str = str(raw_unit_col).strip() if not is_missing_value(raw_unit_col) else "mg/dL"
            row_prov = _resolve_row_provenance(
                row, source_verified_native_export=source_verified_native_export
            )

            # 1. CGM reading (FreeStyle Libre H, 15-min sensor capture)
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
                    g_key = (ts_utc, "cgm", FREESTYLE_LIBRE_H_DEVICE)
                    if g_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cgm",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(g_key)
                        provenance_counts[row_prov] = provenance_counts.get(row_prov, 0) + 1
                        db.add(
                            GlucoseReading(
                                patient_id=patient.id,
                                cohort_type="research_participant",
                                dataset_import_id=dataset_import.id,
                                recorded_at=ts_utc,
                                raw_timestamp=raw_ts_str,
                                timestamp_semantics="real_world_local",
                                timezone_basis=tz_basis,
                                glucose_mg_dl=g_mg_dl,
                                raw_value=g_raw,
                                raw_unit=g_unit,
                                reading_type="cgm",
                                device_id=FREESTYLE_LIBRE_H_DEVICE,
                                sampling_interval_min=SHANGHAI_CGM_INTERVAL_MIN,
                                observation_provenance=row_prov,
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

            # 2. CBG fingerstick reading (never stamped as 'native' CGM)
            cbg_raw = _extract_column(row, ("cbg (mg / dl)", "cbg (mg/dl)", "cbg"))
            if not is_missing_value(cbg_raw):
                try:
                    c_mg_dl, c_raw, c_unit = normalize_glucose_reading(cbg_raw, unit_str)
                    c_key = (ts_utc, "cbg", "__none__")
                    if c_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cbg",
                            reason="duplicate_timestamp",
                            raw_payload=row,
                        )
                    else:
                        existing_glucose_keys.add(c_key)
                        cbg_prov: ObservationProvenanceType = "unknown"
                        provenance_counts[cbg_prov] = provenance_counts.get(cbg_prov, 0) + 1
                        db.add(
                            GlucoseReading(
                                patient_id=patient.id,
                                cohort_type="research_participant",
                                dataset_import_id=dataset_import.id,
                                recorded_at=ts_utc,
                                raw_timestamp=raw_ts_str,
                                timestamp_semantics="real_world_local",
                                timezone_basis=tz_basis,
                                glucose_mg_dl=c_mg_dl,
                                raw_value=c_raw,
                                raw_unit=c_unit,
                                reading_type="cbg",
                                device_id=None,
                                sampling_interval_min=None,
                                observation_provenance=cbg_prov,
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

            # 3. Dietary intake -> Meal
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
                        raw_timestamp=raw_ts_str,
                        timestamp_semantics="real_world_local",
                        timezone_basis=tz_basis,
                        meal_type="unknown",
                        description=str(diet_raw).strip(),
                        ingredients=[],
                        carbs_g=carbs_val,
                        source_dataset=DATASET_NAME,
                        source_record_id=f"{rec_id}:meal",
                    )
                )
                tracker.accept()

            # 4. Timestamped Medication notations -> Medication + MedicationEvent(status='unknown')
            # Suppress ONLY contiguous 15-min spreadsheet fill-down cells (or explicit is_fill_down=True).
            # Preserve genuine separate timestamped administrations (e.g., morning and evening doses).
            sheet_raw = _extract_column(row, ("source_sheet", "sheet_name", "sheet"))
            sheet_name = str(sheet_raw).strip()[:128] if not is_missing_value(sheet_raw) else f"{clean_ext_id}_Sheet1"
            explicit_fill_down = row.get("is_fill_down")

            for med_col_candidates, drug_class, default_col_letter in (
                (
                    ("non-insulin hypoglycemic agents", "oral hypoglycemic agents"),
                    "non_insulin_hypoglycemic",
                    "G",
                ),
                (
                    ("insulin dose - s.c.", "insulin dose - i.v.", "insulin dose"),
                    "insulin",
                    "H",
                ),
            ):
                med_text = _extract_column(row, med_col_candidates)
                if is_missing_value(med_text):
                    last_contiguous_med_by_class[drug_class] = None
                    continue

                med_str = str(med_text).strip()
                if med_str.lower() in {"none", "no", "0"}:
                    last_contiguous_med_by_class[drug_class] = None
                    continue

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

                cell_ref_raw = _extract_column(row, ("source_cell_ref", "cell_ref", "cell"))
                cell_ref = (
                    str(cell_ref_raw).strip()[:64]
                    if not is_missing_value(cell_ref_raw)
                    else f"{default_col_letter}{idx + 2}"
                )

                prev_state = last_contiguous_med_by_class.get(drug_class)
                is_contiguous_fill_down = False
                if explicit_fill_down is True:
                    is_contiguous_fill_down = True
                elif explicit_fill_down is False:
                    is_contiguous_fill_down = False
                elif prev_state is not None:
                    prev_med_str, prev_ts_utc, prev_sheet = prev_state
                    elapsed = ts_utc - prev_ts_utc
                    if (
                        prev_med_str == med_str
                        and prev_sheet == sheet_name
                        and timedelta(0) <= elapsed <= timedelta(minutes=SHANGHAI_CGM_INTERVAL_MIN)
                    ):
                        is_contiguous_fill_down = True

                last_contiguous_med_by_class[drug_class] = (med_str, ts_utc, sheet_name)
                if is_contiguous_fill_down:
                    continue

                db.add(
                    MedicationEvent(
                        patient_id=patient.id,
                        cohort_type="research_participant",
                        medication_id=med_obj.id,
                        event_time=ts_utc,
                        status="unknown",
                        event_source="clinical_record",
                        source_sheet=sheet_name,
                        source_cell_ref=cell_ref,
                        notes=med_str,
                        source_dataset=DATASET_NAME,
                        source_record_id=f"{rec_id}:med_event:{drug_class}",
                    )
                )
                tracker.accept()

    primary_tz_basis = (
        sorted(observed_timezone_bases)[0]
        if len(observed_timezone_bases) == 1
        else ("assumed_study_location" if "assumed_study_location" in observed_timezone_bases else "source_confirmed")
    )

    dataset_import.status = "completed"
    dataset_import.records_accepted = tracker.accepted_count
    dataset_import.records_rejected = tracker.rejected_count
    dataset_import.completed_at = datetime.now(timezone.utc)
    dataset_import.quality_report_summary = tracker.to_quality_report(
        extra={
            "participants_ingested": participants_ingested,
            "license_identifier": LICENSE_IDENTIFIER,
            "license_url": LICENSE_URL,
            "figshare_collection_doi": DEFAULT_COLLECTION_DOI,
            "figshare_item_doi": dataset_doi,
            "source_url": source_url,
            "native_cgm_device": FREESTYLE_LIBRE_H_DEVICE,
            "native_sampling_interval_min": SHANGHAI_CGM_INTERVAL_MIN,
            "timestamp_semantics": "real_world_local",
            "timezone_basis": sorted(observed_timezone_bases) or [primary_tz_basis],
            "assumed_iana_timezone": assumed_iana_tz,
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
        observation_provenance_counts=provenance_counts,
        timestamp_semantics="real_world_local",
        timezone_basis=primary_tz_basis,
    )
