import argparse
import json
from pathlib import Path
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.ingestion.cgmacros import (
    DEFAULT_DATASET_DOI as CGMACROS_DOI,
    DEFAULT_DATASET_VERSION as CGMACROS_VERSION,
    DEFAULT_SOURCE_URL as CGMACROS_URL,
    ingest_cgmacros_archive,
)
from app.ingestion.shanghai_t2dm import (
    CANONICAL_DATASET_DOI as SHANGHAI_DOI,
    CANONICAL_DATASET_VERSION as SHANGHAI_VERSION,
    CANONICAL_SOURCE_URL as SHANGHAI_URL,
    ingest_shanghai_t2dm_archive,
)
from app.models import (
    ActivityRecord,
    ClinicalRecord,
    DatasetImport,
    GlucoseReading,
    Meal,
    Medication,
    MedicationEvent,
    Patient,
)


def run_archive_ingestion(
    *,
    dataset: str,
    archive_path: Path | str,
    dataset_version: str | None = None,
    dataset_doi: str | None = None,
    source_url: str | None = None,
    source_verified_native_export: bool = False,
    native_evidence_reference: str | None = None,
    rollback_after: bool = False,
) -> dict[str, Any]:
    """Run archive ingestion against PostgreSQL and return detailed counts and provenance."""
    engine = get_engine()
    conn = engine.connect()
    outer_tx = conn.begin() if rollback_after else None
    db = (
        Session(bind=conn, join_transaction_mode="create_savepoint")
        if rollback_after
        else Session(bind=conn)
    )
    try:
        ds = dataset.strip().lower()
        if ds in {"shanghai", "shanghai_t2dm"}:
            summary = ingest_shanghai_t2dm_archive(
                db,
                archive_path,
                dataset_version=dataset_version or SHANGHAI_VERSION,
                dataset_doi=dataset_doi or SHANGHAI_DOI,
                source_url=source_url or SHANGHAI_URL,
                source_verified_native_export=source_verified_native_export,
                native_evidence_reference=native_evidence_reference,
            )
        elif ds == "cgmacros":
            summary = ingest_cgmacros_archive(
                db,
                archive_path,
                dataset_version=dataset_version or CGMACROS_VERSION,
                dataset_doi=dataset_doi or CGMACROS_DOI,
                source_url=source_url or CGMACROS_URL,
                source_verified_native_export=source_verified_native_export,
                native_evidence_reference=native_evidence_reference,
            )
        else:
            raise ValueError(f"Unsupported dataset: {dataset!r}. Expected 'shanghai' or 'cgmacros'.")

        import_uuid = uuid.UUID(summary.dataset_import_id)
        imp_row = db.get(DatasetImport, import_uuid)
        q_rep = (imp_row.quality_report_summary or {}) if imp_row else {}

        cgm_count = int(
            db.scalar(
                select(func.count(GlucoseReading.id)).where(
                    GlucoseReading.dataset_import_id == import_uuid,
                    GlucoseReading.reading_type == "cgm",
                )
            )
            or 0
        )
        cbg_count = int(
            db.scalar(
                select(func.count(GlucoseReading.id)).where(
                    GlucoseReading.dataset_import_id == import_uuid,
                    GlucoseReading.reading_type == "cbg",
                )
            )
            or 0
        )
        meals_count = int(
            db.scalar(
                select(func.count(Meal.id)).where(Meal.dataset_import_id == import_uuid)
            )
            or 0
        )
        meds_count = int(
            db.scalar(
                select(func.count(Medication.id)).where(
                    Medication.dataset_import_id == import_uuid
                )
            )
            or 0
        )
        patient_ids = list(
            db.scalars(
                select(Patient.id).where(Patient.dataset_import_id == import_uuid)
            ).all()
        )
        med_events_count = (
            int(
                db.scalar(
                    select(func.count(MedicationEvent.id)).where(
                        MedicationEvent.patient_id.in_(patient_ids)
                    )
                )
                or 0
            )
            if patient_ids
            else 0
        )
        clin_count = int(
            db.scalar(
                select(func.count(ClinicalRecord.id)).where(
                    ClinicalRecord.dataset_import_id == import_uuid
                )
            )
            or 0
        )
        act_count = (
            int(
                db.scalar(
                    select(func.count(ActivityRecord.id)).where(
                        ActivityRecord.patient_id.in_(patient_ids)
                    )
                )
                or 0
            )
            if patient_ids
            else 0
        )

        return {
            "dataset_import_id": summary.dataset_import_id,
            "dataset_name": summary.dataset_name,
            "dataset_version": summary.dataset_version,
            "dataset_doi": summary.dataset_doi,
            "source_url": summary.source_url,
            "license_identifier": summary.license_identifier,
            "source_file_checksum": summary.source_file_checksum,
            "input_payload_checksum": summary.input_payload_checksum,
            "participants_ingested": summary.participants_ingested,
            "excluded_non_t2d_participants": summary.excluded_non_t2d_participants,
            "total_sheets_read": q_rep.get("total_sheets_read"),
            "archive_member_count": q_rep.get("archive_member_count"),
            "cgm_rows_ingested": cgm_count,
            "cbg_rows_ingested": cbg_count,
            "meals_ingested": meals_count,
            "medication_regimens_ingested": meds_count,
            "medication_events_ingested": med_events_count,
            "clinical_records_ingested": clin_count,
            "activity_records_ingested": act_count,
            "records_accepted": summary.records_accepted,
            "records_rejected": summary.records_rejected,
            "rejection_reasons": summary.rejection_reasons,
            "observation_provenance_counts": summary.observation_provenance_counts,
            "timestamp_semantics": summary.timestamp_semantics,
            "timezone_basis": summary.timezone_basis,
        }
    finally:
        db.close()
        if outer_tx is not None:
            outer_tx.rollback()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run GlyCadence dataset archive ingestion with zip-slip protection and SHA-256 provenance."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        choices=["shanghai", "shanghai_t2dm", "cgmacros"],
        help="Target dataset to ingest.",
    )
    parser.add_argument(
        "--archive",
        required=True,
        help="Path to the downloaded .zip archive file.",
    )
    parser.add_argument("--dataset-version", default=None, help="Optional dataset version string.")
    parser.add_argument("--dataset-doi", default=None, help="Optional dataset DOI string.")
    parser.add_argument("--source-url", default=None, help="Optional source download URL.")
    parser.add_argument(
        "--source-verified-native-export",
        action="store_true",
        default=False,
        help="Mark CGM readings as native only when accompanied by --native-evidence-reference.",
    )
    parser.add_argument(
        "--native-evidence-reference",
        default=None,
        help="Required citation/evidence reference if --source-verified-native-export is set.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        default=False,
        help="Rollback DB transaction after computing ingestion summary and counts.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write the JSON summary output.",
    )
    args = parser.parse_args()

    result = run_archive_ingestion(
        dataset=args.dataset,
        archive_path=args.archive,
        dataset_version=args.dataset_version,
        dataset_doi=args.dataset_doi,
        source_url=args.source_url,
        source_verified_native_export=args.source_verified_native_export,
        native_evidence_reference=args.native_evidence_reference,
        rollback_after=args.rollback,
    )
    formatted = json.dumps(result, indent=2, ensure_ascii=False)
    print(formatted)
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
