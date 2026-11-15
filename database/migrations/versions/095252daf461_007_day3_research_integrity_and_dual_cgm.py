"""007_day3_research_integrity_and_dual_cgm

Revision ID: 095252daf461
Revises: 154c4ef16b64
Create Date: 2026-11-15 12:38:13.327067
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '095252daf461'
down_revision: Union[str, Sequence[str], None] = '154c4ef16b64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dataset_imports', sa.Column('license_identifier', sa.String(length=64), nullable=True))
    op.add_column('dataset_imports', sa.Column('input_payload_checksum', sa.String(length=64), nullable=True))
    op.alter_column(
        'dataset_imports',
        'source_file_checksum',
        existing_type=sa.VARCHAR(length=64),
        nullable=True,
    )
    op.create_check_constraint(
        'ck_dataset_imports_checksum_present',
        'dataset_imports',
        'source_file_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL',
    )

    op.add_column('glucose_readings', sa.Column('raw_timestamp', sa.String(length=64), nullable=True))
    op.add_column(
        'glucose_readings',
        sa.Column('timestamp_semantics', sa.String(length=32), server_default=sa.text("'utc_exact'"), nullable=False),
    )
    op.add_column(
        'glucose_readings',
        sa.Column('observation_provenance', sa.String(length=32), server_default=sa.text("'native'"), nullable=False),
    )
    op.create_check_constraint(
        'ck_glucose_timestamp_semantics',
        'glucose_readings',
        "timestamp_semantics IN ('utc_exact', 'real_world_local', 'date_shifted_relative')",
    )
    op.create_check_constraint(
        'ck_glucose_observation_provenance',
        'glucose_readings',
        "observation_provenance IN ('native', 'interpolated', 'derived', 'unknown')",
    )
    op.create_index(
        'uq_glucose_patient_time_type_device',
        'glucose_readings',
        ['patient_id', 'recorded_at', 'reading_type', sa.literal_column("COALESCE(device_id, '__none__')")],
        unique=True,
    )

    op.add_column('meals', sa.Column('raw_timestamp', sa.String(length=64), nullable=True))
    op.add_column(
        'meals',
        sa.Column('timestamp_semantics', sa.String(length=32), server_default=sa.text("'utc_exact'"), nullable=False),
    )
    op.create_check_constraint(
        'ck_meals_timestamp_semantics',
        'meals',
        "timestamp_semantics IN ('utc_exact', 'real_world_local', 'date_shifted_relative')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_meals_timestamp_semantics', 'meals', type_='check')
    op.drop_column('meals', 'timestamp_semantics')
    op.drop_column('meals', 'raw_timestamp')

    op.drop_index('uq_glucose_patient_time_type_device', table_name='glucose_readings')
    op.drop_constraint('ck_glucose_observation_provenance', 'glucose_readings', type_='check')
    op.drop_constraint('ck_glucose_timestamp_semantics', 'glucose_readings', type_='check')
    op.drop_column('glucose_readings', 'observation_provenance')
    op.drop_column('glucose_readings', 'timestamp_semantics')
    op.drop_column('glucose_readings', 'raw_timestamp')

    op.drop_constraint('ck_dataset_imports_checksum_present', 'dataset_imports', type_='check')
    op.execute(
        "UPDATE dataset_imports SET source_file_checksum = COALESCE(source_file_checksum, input_payload_checksum, 'unknown') WHERE source_file_checksum IS NULL"
    )
    op.alter_column(
        'dataset_imports',
        'source_file_checksum',
        existing_type=sa.VARCHAR(length=64),
        nullable=False,
    )
    op.drop_column('dataset_imports', 'input_payload_checksum')
    op.drop_column('dataset_imports', 'license_identifier')
