"""008_dataset_import_provenance_immutability_and_timezone_basis

Revision ID: 2fbaca9193d3
Revises: 095252daf461
Create Date: 2026-11-15 13:19:46.308571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fbaca9193d3'
down_revision: Union[str, Sequence[str], None] = '095252daf461'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. DatasetImport provenance columns & updated checksum constraint
    op.add_column('dataset_imports', sa.Column('dataset_doi', sa.String(length=128), nullable=True))
    op.add_column('dataset_imports', sa.Column('source_url', sa.String(length=255), nullable=True))
    op.add_column('dataset_imports', sa.Column('license_url', sa.String(length=255), nullable=True))
    op.add_column('dataset_imports', sa.Column('directory_manifest_checksum', sa.String(length=64), nullable=True))

    op.drop_constraint('ck_dataset_imports_checksum_present', 'dataset_imports', type_='check')
    op.create_check_constraint(
        'ck_dataset_imports_checksum_present',
        'dataset_imports',
        'source_file_checksum IS NOT NULL OR directory_manifest_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL',
    )

    # 2. Timezone basis on glucose_readings and meals
    op.add_column(
        'glucose_readings',
        sa.Column('timezone_basis', sa.String(length=32), server_default=sa.text("'source_confirmed'"), nullable=False),
    )
    op.create_check_constraint(
        'ck_glucose_timezone_basis',
        'glucose_readings',
        "timezone_basis IN ('source_confirmed', 'assumed_study_location', 'unknown', 'not_applicable_relative')",
    )

    op.add_column(
        'meals',
        sa.Column('timezone_basis', sa.String(length=32), server_default=sa.text("'source_confirmed'"), nullable=False),
    )
    op.create_check_constraint(
        'ck_meals_timezone_basis',
        'meals',
        "timezone_basis IN ('source_confirmed', 'assumed_study_location', 'unknown', 'not_applicable_relative')",
    )

    # 3. Source sheet / cell reference provenance on medication_events
    op.add_column('medication_events', sa.Column('source_sheet', sa.String(length=128), nullable=True))
    op.add_column('medication_events', sa.Column('source_cell_ref', sa.String(length=64), nullable=True))

    # 4. Protect completed dataset_imports provenance via database trigger
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_completed_dataset_import_provenance()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'completed' THEN
                    RAISE EXCEPTION 'Completed dataset_imports provenance records are immutable and cannot be deleted (id=%)', OLD.id;
                END IF;
                RETURN OLD;
            END IF;

            IF TG_OP = 'UPDATE' AND OLD.status = 'completed' THEN
                IF NEW.dataset_name IS DISTINCT FROM OLD.dataset_name
                   OR NEW.dataset_version IS DISTINCT FROM OLD.dataset_version
                   OR NEW.dataset_doi IS DISTINCT FROM OLD.dataset_doi
                   OR NEW.source_url IS DISTINCT FROM OLD.source_url
                   OR NEW.license_identifier IS DISTINCT FROM OLD.license_identifier
                   OR NEW.license_url IS DISTINCT FROM OLD.license_url
                   OR NEW.source_file_checksum IS DISTINCT FROM OLD.source_file_checksum
                   OR NEW.directory_manifest_checksum IS DISTINCT FROM OLD.directory_manifest_checksum
                   OR NEW.input_payload_checksum IS DISTINCT FROM OLD.input_payload_checksum
                   OR NEW.preprocessing_version IS DISTINCT FROM OLD.preprocessing_version
                   OR NEW.status IS DISTINCT FROM OLD.status
                THEN
                    RAISE EXCEPTION 'Completed dataset_imports provenance fields are immutable and cannot be modified (id=%)', OLD.id;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dataset_imports_protect_completed_provenance
        BEFORE UPDATE OR DELETE ON dataset_imports
        FOR EACH ROW
        EXECUTE FUNCTION protect_completed_dataset_import_provenance();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_dataset_imports_protect_completed_provenance ON dataset_imports;")
    op.execute("DROP FUNCTION IF EXISTS protect_completed_dataset_import_provenance();")

    op.drop_column('medication_events', 'source_cell_ref')
    op.drop_column('medication_events', 'source_sheet')

    op.drop_constraint('ck_meals_timezone_basis', 'meals', type_='check')
    op.drop_column('meals', 'timezone_basis')

    op.drop_constraint('ck_glucose_timezone_basis', 'glucose_readings', type_='check')
    op.drop_column('glucose_readings', 'timezone_basis')

    op.drop_constraint('ck_dataset_imports_checksum_present', 'dataset_imports', type_='check')
    op.create_check_constraint(
        'ck_dataset_imports_checksum_present',
        'dataset_imports',
        'source_file_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL',
    )

    op.drop_column('dataset_imports', 'directory_manifest_checksum')
    op.drop_column('dataset_imports', 'license_url')
    op.drop_column('dataset_imports', 'source_url')
    op.drop_column('dataset_imports', 'dataset_doi')
