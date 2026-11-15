from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.ingestion.common import (
    MMOL_L_TO_MG_DL,
    PREPROCESSING_VERSION,
    IngestionSummary,
    ObservationProvenanceType,
    RejectionTracker,
    compute_input_payload_checksum,
    compute_source_file_checksum,
    extract_zip_safely,
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
CANONICAL_DATASET_VERSION = "figshare-item-20444397-v3"
CANONICAL_DATASET_DOI = "10.6084/m9.figshare.20444397.v3"
CANONICAL_SOURCE_URL = "https://ndownloader.figshare.com/files/38259264"
LEGACY_V1_DATASET_VERSION = "figshare-item-20444397-v1"
LEGACY_V1_DATASET_DOI = "10.6084/m9.figshare.20444397.v1"
LEGACY_V1_SOURCE_URL = "https://ndownloader.figshare.com/files/36582306"
DEFAULT_DATASET_VERSION = LEGACY_V1_DATASET_VERSION
DEFAULT_DATASET_DOI = LEGACY_V1_DATASET_DOI
DEFAULT_COLLECTION_DOI = "10.6084/m9.figshare.c.6310860.v1"
DEFAULT_SOURCE_URL = LEGACY_V1_SOURCE_URL
LICENSE_IDENTIFIER = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
FREESTYLE_LIBRE_H_DEVICE = "FreeStyle_Libre_H"
SHANGHAI_CGM_INTERVAL_MIN = 15
SHANGHAI_V3_PAPER_CITATION = (
    "Zhao et al., Scientific Data 10:35 (2023) doi:10.1038/s41597-023-01940-7"
)
VALID_PROVENANCES: set[str] = {
    "native",
    "dataset_documented",
    "archive_aligned",
    "interpolated",
    "derived",
    "unknown",
}


def _excel_col_letter(col_idx: int) -> str:
    """Convert a 0-based column index into a 1-based Excel column letter (0 -> 'A', 25 -> 'Z', 26 -> 'AA')."""
    result = ""
    n = col_idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _strip_internal_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not str(k).startswith("_real_")}


def _load_tabular(
    source: Path | pd.DataFrame | list[dict[str, Any]],
    *,
    include_excel_metadata: bool = False,
) -> list[dict[str, Any]]:
    """Load tabular data from list[dict], DataFrame, CSV, or multi-sheet Excel workbooks.

    When reading an Excel workbook (``.xlsx`` / ``.xls``), iterates over ALL sheets via
    ``pd.read_excel(path, sheet_name=None)`` and, when ``include_excel_metadata=True``,
    attaches real sheet names, real 1-based Excel row numbers (``row_idx + 2``), and real
    column letters per header.
    """
    if isinstance(source, list):
        return [dict(r) for r in source]
    if isinstance(source, pd.DataFrame):
        return source.to_dict(orient="records")
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        sheets_dict = pd.read_excel(path, sheet_name=None)
        all_rows: list[dict[str, Any]] = []
        for sheet_name, df in sheets_dict.items():
            col_letters = {
                str(col_name).strip().lower(): _excel_col_letter(c_idx)
                for c_idx, col_name in enumerate(df.columns)
            }
            records = df.to_dict(orient="records")
            for r_idx, rec in enumerate(records):
                if include_excel_metadata:
                    rec = dict(rec)
                    rec["_real_source_sheet"] = str(sheet_name)[:128]
                    rec["_real_excel_row"] = int(r_idx) + 2
                    rec["_real_col_letters"] = col_letters
                all_rows.append(rec)
        return all_rows
    if suffix == ".csv":
        df = pd.read_csv(path)
        return df.to_dict(orient="records")
    raise ValueError(f"Unsupported ShanghaiT2DM file format: {suffix}")


def _normalize_sex(raw_sex: Any) -> str | None:
    """Normalize sex/gender field.

    In ShanghaiT2DM workbooks, the column header is explicitly ``Gender (Female=1, Male=2)``
    (or Chinese ``性别（女1，男2）``), so ``1`` = female and ``2`` = male.
    """
    if is_missing_value(raw_sex):
        return None
    s = str(raw_sex).strip().lower()
    if s in {"1", "1.0", "f", "female", "woman", "女"}:
        return "female"
    if s in {"2", "2.0", "m", "male", "man", "男"}:
        return "male"
    return s[:32]


def _extract_column_with_key(
    row: dict[str, Any], candidates: tuple[str, ...]
) -> tuple[Any, str | None]:
    lower_map = {
        str(k).strip().lower(): v
        for k, v in row.items()
        if not str(k).startswith("_real_")
    }
    for cand in candidates:
        c_low = cand.lower()
        if c_low in lower_map:
            return lower_map[c_low], c_low
    return None, None


def _extract_column(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    val, _ = _extract_column_with_key(row, candidates)
    return val


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
    dataset_documented_export: bool = False,
) -> ObservationProvenanceType:
    explicit = _extract_column(row, ("observation_provenance", "cgm_provenance", "provenance"))
    if not is_missing_value(explicit):
        cleaned = str(explicit).strip().lower()
        if cleaned in VALID_PROVENANCES:
            return cleaned  # type: ignore[return-value]
    if source_verified_native_export:
        return "native"
    if dataset_documented_export:
        return "dataset_documented"
    return "unknown"


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
    dataset_documented_export: bool = False,
    native_evidence_reference: str | None = None,
    participant_consent_version: str | None = None,
    extra_quality_metadata: dict[str, Any] | None = None,
) -> IngestionSummary:
    """Ingest ShanghaiT2DM research participant data with strict provenance & validation.

    Non-negotiable rules enforced:
    - Figshare item/version (``10.6084/m9.figshare.20444397.v3`` canonical or ``v1`` legacy)
      and license ``CC BY 4.0`` recorded on ``DatasetImport`` — never stored in ``Patient.consent_version``.
    - ``source_verified_native_export=True`` or ``dataset_documented_export=True`` requires a non-empty
      ``native_evidence_reference`` citation (with ``10.1038/s41597-023-01940-7`` required for
      ``dataset_documented_export=True``), recorded in ``dataset_imports.quality_report_summary`` and ``audit_logs``.
    - CBG / finger-stick rows are never stamped as ``native`` or ``dataset_documented`` CGM.
    """
    if (source_verified_native_export or dataset_documented_export) and (
        native_evidence_reference is None or not str(native_evidence_reference).strip()
    ):
        raise ValueError(
            "native_evidence_reference is required when source_verified_native_export=True or dataset_documented_export=True"
        )
    if dataset_documented_export and "10.1038/s41597-023-01940-7" not in str(native_evidence_reference):
        raise ValueError(
            "native_evidence_reference must cite DOI 10.1038/s41597-023-01940-7 when dataset_documented_export=True"
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
        for srow in _load_tabular(summary_source, include_excel_metadata=False):
            raw_pid = _extract_column(
                srow, ("patient number", "patient_id", "subject_id", "id", "患者编号")
            )
            if not is_missing_value(raw_pid):
                if isinstance(raw_pid, float) and raw_pid.is_integer():
                    ext_key = str(int(raw_pid))
                else:
                    ext_key = str(raw_pid).strip()
                merged = dict(summary_by_ext_id.get(ext_key, {}))
                merged.update(srow)
                summary_by_ext_id[ext_key] = merged
                base_id = ext_key.split("_")[0]
                base_merged = dict(summary_by_ext_id.get(base_id, {}))
                base_merged.update(srow)
                summary_by_ext_id[base_id] = base_merged

    participants_ingested = 0
    seen_base_participants: set[str] = set()
    total_sheets_read = 0
    provenance_counts: dict[str, int] = {
        "native": 0,
        "dataset_documented": 0,
        "archive_aligned": 0,
        "interpolated": 0,
        "derived": 0,
        "unknown": 0,
    }
    observed_timezone_bases: set[str] = set()

    for ext_id, ts_source in participant_sources.items():
        clean_ext_id = str(ext_id).strip()
        base_ext_id = clean_ext_id.split("_")[0]
        srow = summary_by_ext_id.get(clean_ext_id) or summary_by_ext_id.get(base_ext_id) or {}

        declared_type = _extract_column(
            srow,
            (
                "diabetes_type",
                "type of diabetes",
                "type of diabetes (t1dm：1；t2dm：2)",
                "糖尿病类型（t1dm：1；t2dm：2）",
                "type",
            ),
        )
        if not is_missing_value(declared_type) and str(declared_type).strip().upper() in {
            "T1D",
            "T1DM",
            "1",
            "1.0",
        }:
            tracker.reject(
                source_record_id=f"{clean_ext_id}:summary",
                reason="t1d_cohort_mixing_forbidden",
                raw_payload={"external_id": clean_ext_id, "diabetes_type": declared_type},
            )
            continue

        raw_age = _extract_column(srow, ("age (years)", "age (year)", "age", "年龄"))
        age_val: int | None = None
        if not is_missing_value(raw_age):
            try:
                parsed_age = int(float(raw_age))
                if 1 <= parsed_age <= 120:
                    age_val = parsed_age
            except (TypeError, ValueError):
                pass

        raw_height = _extract_column(srow, ("height (m)", "height (cm)", "height", "身高m"))
        height_cm: float | None = None
        if not is_missing_value(raw_height):
            try:
                h_val = float(raw_height)
                cand_cm = round(h_val * 100.0, 1) if h_val < 3.0 else round(h_val, 1)
                if 20.0 <= cand_cm <= 260.0:
                    height_cm = cand_cm
            except (TypeError, ValueError):
                pass

        raw_weight = _extract_column(srow, ("weight (kg)", "weight", "体重kg"))
        weight_kg: float | None = None
        if not is_missing_value(raw_weight):
            try:
                cand_kg = round(float(raw_weight), 1)
                if 1.0 <= cand_kg <= 450.0:
                    weight_kg = cand_kg
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
                sex=_normalize_sex(
                    _extract_column(
                        srow,
                        (
                            "gender (female=1, male=2)",
                            "gender（female1，male2）",
                            "性别（女1，男2）",
                            "gender",
                            "sex",
                        ),
                    )
                ),
                diabetes_type="T2D",
                height_cm=height_cm,
                weight_kg=weight_kg,
                timezone=assumed_iana_tz,
                consent_granted=bool(participant_consent_version),
                consent_version=participant_consent_version,
                retention_policy="dataset_license_bound",
                source_dataset=DATASET_NAME,
            )
            db.add(patient)
            db.flush()
        if base_ext_id not in seen_base_participants:
            seen_base_participants.add(base_ext_id)
            participants_ingested += 1

        known_meds: dict[str, Medication] = {
            m.medication_name: m
            for m in db.scalars(
                select(Medication).where(Medication.patient_id == patient.id)
            ).all()
        }

        # Static medication regimen descriptions in summary sheet create Medication rows ONLY (never MedicationEvents)
        for sum_med_cols, sum_drug_class in (
            (
                (
                    "hypoglycemic agents",
                    "non-insulin hypoglycemic agents",
                    "oral hypoglycemic agents",
                    "diabetes medication",
                    "糖尿病用药",
                ),
                "non_insulin_hypoglycemic",
            ),
            (("insulin", "insulin regimen"), "insulin"),
        ):
            sum_med_raw = _extract_column(srow, sum_med_cols)
            if not is_missing_value(sum_med_raw):
                sum_med_str = str(sum_med_raw).strip()
                if sum_med_str.lower() not in {"none", "no", "0", "无"}:
                    if sum_med_str[:255] not in known_meds:
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
                        known_meds[sum_med_str[:255]] = med_obj
                        tracker.accept()

        raw_rows = _load_tabular(ts_source, include_excel_metadata=True)
        sheets_in_source = {
            r.get("_real_source_sheet")
            for r in raw_rows
            if r.get("_real_source_sheet") is not None
        }
        total_sheets_read += max(1, len(sheets_in_source)) if raw_rows else 0

        parsed_rows: list[tuple[int, datetime, str, str, dict[str, Any]]] = []
        for idx, row in enumerate(raw_rows):
            sheet_tag = row.get("_real_source_sheet")
            row_num_tag = row.get("_real_excel_row")
            rec_id = (
                f"{clean_ext_id}:{sheet_tag}:row_{row_num_tag}"
                if sheet_tag and row_num_tag
                else f"{clean_ext_id}:row_{idx}"
            )
            raw_ts = _extract_column(row, ("date", "timestamp", "recorded_at", "time"))
            try:
                ts_utc, raw_ts_str, _, tz_basis = parse_timestamp_with_semantics(
                    raw_ts,
                    semantics="real_world_local",
                    assumed_iana_tz=assumed_iana_tz,
                )
            except ValueError as err:
                tracker.reject(
                    source_record_id=rec_id,
                    reason=str(err),
                    raw_payload=_strip_internal_meta(row),
                )
                continue
            observed_timezone_bases.add(tz_basis)
            parsed_rows.append((idx, ts_utc, raw_ts_str, tz_basis, row))

        parsed_rows.sort(key=lambda item: (item[1], item[0]))

        if srow and parsed_rows:
            first_ts = parsed_rows[0][1]
            hba1c_val: float | None = None
            raw_hba1c_pct = _extract_column(srow, ("hba1c (%)", "hba1c(%)", "hba1c", "a1c"))
            raw_hba1c_ifcc = _extract_column(srow, ("hba1c (mmol/mol)",))
            if not is_missing_value(raw_hba1c_pct):
                try:
                    cand = float(raw_hba1c_pct)
                    hba1c_val = round(0.09148 * cand + 2.152, 2) if cand > 25.0 else round(cand, 2)
                except (TypeError, ValueError):
                    pass
            elif not is_missing_value(raw_hba1c_ifcc):
                try:
                    hba1c_val = round(0.09148 * float(raw_hba1c_ifcc) + 2.152, 2)
                except (TypeError, ValueError):
                    pass
            if hba1c_val is not None and not (2.0 <= hba1c_val <= 25.0):
                hba1c_val = None

            bmi_val: float | None = None
            raw_bmi = _extract_column(srow, ("bmi (kg/m2)", "bmi"))
            if not is_missing_value(raw_bmi):
                try:
                    cand_bmi = round(float(raw_bmi), 2)
                    if 8.0 <= cand_bmi <= 100.0:
                        bmi_val = cand_bmi
                except (TypeError, ValueError):
                    pass

            fpg_val: float | None = None
            raw_fpg_mg = _extract_column(
                srow, ("fasting plasma glucose (mg/dl)", "fasting glucose", "fpg")
            )
            raw_fpg_mmol = _extract_column(
                srow, ("fasting plasma glucose (mmol/l)", "空腹血糖（mmol/l）")
            )
            if not is_missing_value(raw_fpg_mg):
                try:
                    cand_fpg = round(float(raw_fpg_mg), 2)
                    if 10.0 <= cand_fpg <= 1500.0:
                        fpg_val = cand_fpg
                except (TypeError, ValueError):
                    pass
            elif not is_missing_value(raw_fpg_mmol):
                try:
                    cand_fpg = round(float(raw_fpg_mmol) * MMOL_L_TO_MG_DL, 2)
                    if 10.0 <= cand_fpg <= 1500.0:
                        fpg_val = cand_fpg
                except (TypeError, ValueError):
                    pass

            clin = ClinicalRecord(
                patient_id=patient.id,
                cohort_type="research_participant",
                dataset_import_id=dataset_import.id,
                recorded_at=first_ts,
                hba1c_pct=hba1c_val,
                bmi=bmi_val,
                fasting_glucose_mg_dl=fpg_val,
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

        for idx, ts_utc, raw_ts_str, tz_basis, row in parsed_rows:
            sheet_tag = row.get("_real_source_sheet")
            row_num_tag = row.get("_real_excel_row")
            rec_id = (
                f"{clean_ext_id}:{sheet_tag}:row_{row_num_tag}"
                if sheet_tag and row_num_tag
                else f"{clean_ext_id}:row_{idx}"
            )
            clean_row = _strip_internal_meta(row)
            raw_unit_col = _extract_column(row, ("unit", "raw_unit", "glucose_unit"))
            unit_str = str(raw_unit_col).strip() if not is_missing_value(raw_unit_col) else "mg/dL"
            row_prov = _resolve_row_provenance(
                row,
                source_verified_native_export=source_verified_native_export,
                dataset_documented_export=dataset_documented_export,
            )

            # 1. CGM reading (FreeStyle Libre H, 15-min sensor capture)
            cgm_raw, cgm_col_key = _extract_column_with_key(
                row, ("cgm (mg / dl)", "cgm (mg/dl)", "cgm", "glucose_cgm", "cgm (mmol / l)")
            )
            if not is_missing_value(cgm_raw):
                inferred_unit = (
                    "mmol/L"
                    if (cgm_col_key and "mmol" in cgm_col_key and is_missing_value(raw_unit_col))
                    else unit_str
                )
                try:
                    g_mg_dl, g_raw, g_unit = normalize_glucose_reading(cgm_raw, inferred_unit)
                    g_key = (ts_utc, "cgm", FREESTYLE_LIBRE_H_DEVICE)
                    if g_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cgm",
                            reason="duplicate_timestamp",
                            raw_payload=clean_row,
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
                        raw_payload=clean_row,
                    )

            # 2. CBG fingerstick reading (never stamped as 'native' CGM)
            cbg_raw, cbg_col_key = _extract_column_with_key(
                row,
                ("cbg (mg / dl)", "cbg (mg/dl)", "cbg", "capillary blood glucose"),
            )
            if not is_missing_value(cbg_raw):
                cbg_unit = (
                    "mmol/L"
                    if (
                        cbg_col_key == "capillary blood glucose"
                        and is_missing_value(raw_unit_col)
                    )
                    else unit_str
                )
                try:
                    c_mg_dl, c_raw, c_unit = normalize_glucose_reading(cbg_raw, cbg_unit)
                    c_key = (ts_utc, "cbg", "__none__")
                    if c_key in existing_glucose_keys:
                        tracker.reject(
                            source_record_id=f"{rec_id}:cbg",
                            reason="duplicate_timestamp",
                            raw_payload=clean_row,
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
                        raw_payload=clean_row,
                    )

            # 3. Dietary intake -> Meal
            diet_raw = _extract_column(row, ("dietary intake", "meal", "diet"))
            if not is_missing_value(diet_raw) and str(diet_raw).strip() not in {
                "Data not available",
                "data not available",
                "/",
            }:
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
            # Never fabricate sheet names ('_Sheet1') or cell references ('G{idx+2}'/'H{idx+2}').
            # Preserve every non-empty medication row with its real sheet name and real Excel cell ref
            # when loaded from an Excel workbook, or None (NULL) when unknown.
            explicit_sheet = _extract_column(row, ("source_sheet", "sheet_name", "sheet"))
            if not is_missing_value(explicit_sheet):
                sheet_name: str | None = str(explicit_sheet).strip()[:128]
            elif row.get("_real_source_sheet") is not None:
                sheet_name = str(row["_real_source_sheet"])[:128]
            else:
                sheet_name = None

            explicit_cell_ref = _extract_column(row, ("source_cell_ref", "cell_ref", "cell"))
            real_col_letters: dict[str, str] = row.get("_real_col_letters") or {}
            real_excel_row: int | None = row.get("_real_excel_row")

            for med_col_candidates, drug_class in (
                (
                    ("non-insulin hypoglycemic agents", "oral hypoglycemic agents", "drug usage"),
                    "non_insulin_hypoglycemic",
                ),
                (
                    (
                        "insulin dose - s.c.",
                        "insulin dose - i.v.",
                        "insulin dose",
                        "csii - bolus insulin (novolin r, iu)",
                        "csii - basal insulin (novolin r, iu / h)",
                    ),
                    "insulin",
                ),
            ):
                med_text, matched_med_col = _extract_column_with_key(row, med_col_candidates)
                if is_missing_value(med_text):
                    continue

                med_str = str(med_text).strip()
                if med_str.lower() in {"none", "no", "0", "/", "无"}:
                    continue

                med_key = med_str[:255]
                med_obj = known_meds.get(med_key)
                if med_obj is None:
                    med_obj = Medication(
                        patient_id=patient.id,
                        cohort_type="research_participant",
                        dataset_import_id=dataset_import.id,
                        medication_name=med_key,
                        drug_class=drug_class,
                        recorded_dose=med_str[:128],
                        is_active=True,
                        source_dataset=DATASET_NAME,
                        source_record_id=f"{rec_id}:med_regimen",
                    )
                    db.add(med_obj)
                    db.flush()
                    known_meds[med_key] = med_obj
                    tracker.accept()

                if not is_missing_value(explicit_cell_ref):
                    cell_ref: str | None = str(explicit_cell_ref).strip()[:64]
                elif (
                    matched_med_col is not None
                    and matched_med_col in real_col_letters
                    and real_excel_row is not None
                ):
                    cell_ref = f"{real_col_letters[matched_med_col]}{real_excel_row}"
                else:
                    cell_ref = None

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

    extra_info: dict[str, Any] = {
        "participants_ingested": participants_ingested,
        "total_sheets_read": total_sheets_read,
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
        "dataset_documented_export": dataset_documented_export,
        "native_evidence_reference": cleaned_evidence_ref,
        "observation_provenance_counts": provenance_counts,
    }
    if extra_quality_metadata:
        extra_info.update(extra_quality_metadata)

    dataset_import.status = "completed"
    dataset_import.records_accepted = tracker.accepted_count
    dataset_import.records_rejected = tracker.rejected_count
    dataset_import.completed_at = datetime.now(timezone.utc)
    dataset_import.quality_report_summary = tracker.to_quality_report(extra=extra_info)
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
            "dataset_documented_export": dataset_documented_export,
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


def ingest_shanghai_t2dm_archive(
    db: Session,
    archive_path: Path | str,
    *,
    dataset_version: str = CANONICAL_DATASET_VERSION,
    dataset_doi: str = CANONICAL_DATASET_DOI,
    source_url: str = CANONICAL_SOURCE_URL,
    assumed_iana_tz: str | None = "Asia/Shanghai",
    source_verified_native_export: bool = False,
    dataset_documented_export: bool | None = None,
    native_evidence_reference: str | None = SHANGHAI_V3_PAPER_CITATION,
) -> IngestionSummary:
    """Safely extract a ShanghaiT2DM ZIP archive and ingest all T2DM summary & participant files.

    Defaults to the canonical Figshare v3 release (``data.zip``, ``10.6084/m9.figshare.20444397.v3``)
    matching the 2023 *Scientific Data* publication (100 T2D patients across 109 admissions),
    stamping CGM rows as ``dataset_documented`` with mandatory citation ``10.1038/s41597-023-01940-7``.
    Legacy v1 (``Diabetes_dataset.zip``) is excluded from default pipelines and only ingested when
    explicitly overridden.
    """
    is_v3_documented = (
        (dataset_version == CANONICAL_DATASET_VERSION)
        if dataset_documented_export is None
        else dataset_documented_export
    )
    arch = Path(archive_path)
    archive_sha256 = compute_source_file_checksum(arch)
    with tempfile.TemporaryDirectory(prefix="glycadence_shanghai_") as tmp_dir:
        extracted_files = extract_zip_safely(arch, tmp_dir)
        tmp_root = Path(tmp_dir).resolve()

        summary_file: Path | None = None
        participant_files: dict[str, Path] = {}
        member_sha256: dict[str, str] = {}

        for fpath in sorted(extracted_files):
            rel = fpath.relative_to(tmp_root).as_posix()
            f_hash = compute_source_file_checksum(fpath)
            if f_hash:
                member_sha256[rel] = f_hash

            low_name = fpath.name.lower()
            low_rel = rel.lower()
            if "t1dm" in low_rel:
                continue
            if "t2dm" in low_name and "summary" in low_name:
                summary_file = fpath
            elif low_name in {"shanghait2dm.xlsx", "shanghai_t2dm.xlsx"}:
                summary_file = fpath
            elif fpath.suffix.lower() in {".csv", ".xlsx", ".xls"} and (
                "shanghait2dm/" in low_rel or "shanghai_t2dm/" in low_rel or "_" in fpath.stem
            ):
                participant_files[fpath.stem] = fpath

        return ingest_shanghai_t2dm(
            db,
            participant_sources=participant_files,
            summary_source=summary_file,
            source_file_path=arch,
            dataset_version=dataset_version,
            dataset_doi=dataset_doi,
            source_url=source_url,
            assumed_iana_tz=assumed_iana_tz,
            source_verified_native_export=source_verified_native_export,
            dataset_documented_export=is_v3_documented,
            native_evidence_reference=native_evidence_reference,
            extra_quality_metadata={
                "archive_sha256": archive_sha256,
                "archive_member_count": len(member_sha256),
                "archive_member_sha256": member_sha256,
            },
        )
