"""010_group_e_patient_timezone

Revision ID: 4b82f9d50010
Revises: 3a91e8c40009
Create Date: 2026-11-15 14:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4b82f9d50010"
down_revision: Union[str, None] = "3a91e8c40009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patients", "timezone")
