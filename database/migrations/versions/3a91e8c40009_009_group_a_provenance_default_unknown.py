"""009_group_a_provenance_default_unknown

Revision ID: 3a91e8c40009
Revises: 2fbaca9193d3
Create Date: 2026-11-15 13:50:30.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3a91e8c40009"
down_revision: Union[str, Sequence[str], None] = "2fbaca9193d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "glucose_readings",
        "observation_provenance",
        existing_type=sa.String(length=32),
        server_default=sa.text("'unknown'"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "glucose_readings",
        "observation_provenance",
        existing_type=sa.String(length=32),
        server_default=sa.text("'native'"),
        existing_nullable=False,
    )
