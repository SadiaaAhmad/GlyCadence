"""011_decision_a_provenance_tiers_and_backfill

Revision ID: 5c93a0e60011
Revises: 4b82f9d50010
Create Date: 2026-11-15 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5c93a0e60011"
down_revision: Union[str, Sequence[str], None] = "4b82f9d50010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Expand ck_glucose_observation_provenance to include dataset_documented and archive_aligned
    op.drop_constraint("ck_glucose_observation_provenance", "glucose_readings", type_="check")
    op.create_check_constraint(
        "ck_glucose_observation_provenance",
        "glucose_readings",
        "observation_provenance IN ('native', 'dataset_documented', 'archive_aligned', 'interpolated', 'derived', 'unknown')",
    )

    # 2. Backfill existing research rows safely (compatible with trg_dataset_imports_protect_completed_provenance,
    #    which allows updating quality_report_summary while keeping all immutable dataset_imports columns untouched)
    op.execute(
        """
        UPDATE glucose_readings gr
        SET observation_provenance = 'dataset_documented'
        FROM dataset_imports di
        WHERE gr.dataset_import_id = di.id
          AND gr.source_dataset = 'shanghai_t2dm'
          AND gr.reading_type = 'cgm'
          AND gr.observation_provenance = 'unknown'
          AND di.dataset_version = 'figshare-item-20444397-v3';
        """
    )
    op.execute(
        """
        UPDATE dataset_imports
        SET quality_report_summary = jsonb_set(
            COALESCE(quality_report_summary, '{}'::jsonb),
            '{native_evidence_reference}',
            '"Zhao et al., Scientific Data 10:35 (2023) doi:10.1038/s41597-023-01940-7"'::jsonb,
            true
        )
        WHERE dataset_name = 'shanghai_t2dm'
          AND dataset_version = 'figshare-item-20444397-v3';
        """
    )
    op.execute(
        """
        UPDATE glucose_readings
        SET observation_provenance = 'archive_aligned'
        WHERE source_dataset = 'cgmacros'
          AND reading_type = 'cgm'
          AND observation_provenance = 'unknown';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE glucose_readings
        SET observation_provenance = 'unknown'
        WHERE observation_provenance IN ('dataset_documented', 'archive_aligned');
        """
    )
    op.drop_constraint("ck_glucose_observation_provenance", "glucose_readings", type_="check")
    op.create_check_constraint(
        "ck_glucose_observation_provenance",
        "glucose_readings",
        "observation_provenance IN ('native', 'interpolated', 'derived', 'unknown')",
    )
