"""006_configurable_retention_and_audit_context

Revision ID: 154c4ef16b64
Revises: 7855e3a9f728
Create Date: 2026-11-14 23:59:52.943552
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '154c4ef16b64'
down_revision: Union[str, Sequence[str], None] = '7855e3a9f728'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'audit_logs',
        sa.Column('context_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.drop_constraint('ck_patients_retention_policy', 'patients', type_='check')
    op.create_check_constraint(
        'ck_patients_retention_policy',
        'patients',
        "retention_policy IN ('30_days', '90_days', '180_days', '365_days', 'custom_days', "
        "'indefinite_until_revoked', 'research_archive', 'dataset_license_bound')",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_patient_retention_before_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            IF OLD.cohort_type = 'research_participant'
               OR OLD.retention_policy IN ('research_archive', 'dataset_license_bound') THEN
                RAISE EXCEPTION 'Hard deletion of research_participant or archived/license-bound records is forbidden by retention policy';
            END IF;
            IF OLD.retention_expires_at IS NOT NULL AND OLD.retention_expires_at > NOW() THEN
                RAISE EXCEPTION 'Hard deletion of patient % blocked before retention_expires_at (%)', OLD.id, OLD.retention_expires_at;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.drop_constraint('ck_patients_retention_policy', 'patients', type_='check')
    op.create_check_constraint(
        'ck_patients_retention_policy',
        'patients',
        "retention_policy IN ('365_days', 'indefinite_until_revoked', 'research_archive')",
    )
    op.drop_column('audit_logs', 'context_metadata')
