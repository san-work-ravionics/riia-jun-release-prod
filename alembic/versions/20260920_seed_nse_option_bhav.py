"""seed nse_option_bhav from compressed DB file

Revision ID: 20260920_seed_nse_option_bhav
Revises: 993fec6a43bd
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '20260920_seed_nse_option_bhav'
down_revision: str = '993fec6a43bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nse_option_bhav" in inspector.get_table_names():
        bind.execute(sa.text("DELETE FROM nse_option_bhav"))
