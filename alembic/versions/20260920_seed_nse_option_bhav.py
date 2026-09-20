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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "nse_option_bhav" not in inspector.get_table_names():
        return

    count = bind.execute(sa.text("SELECT COUNT(*) FROM nse_option_bhav")).scalar()
    if count > 0:
        return

    import gzip
    import os
    import shutil
    import tempfile
    from pathlib import Path

    seed_paths = [
        Path("/app/data/input/NIFTY/nse_option_bhav.db.gz"),
        Path(os.environ.get("RITA_INPUT_DIR", "data/input")) / "NIFTY" / "nse_option_bhav.db.gz",
    ]

    gz_path = None
    for p in seed_paths:
        if p.exists():
            gz_path = p
            break

    if gz_path is None:
        return

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        with gzip.open(gz_path, "rb") as f_in:
            shutil.copyfileobj(f_in, tmp)
        tmp_path = tmp.name

    try:
        bind.execute(sa.text(f"ATTACH DATABASE '{tmp_path}' AS seed_db"))
        bind.execute(sa.text(
            "INSERT INTO nse_option_bhav "
            "(date, strike, option_type, expiry, open, high, low, close, settle_price, oi) "
            "SELECT date, strike, option_type, expiry, open, high, low, close, settle_price, oi "
            "FROM seed_db.nse_option_bhav"
        ))
        bind.execute(sa.text("DETACH DATABASE seed_db"))
    finally:
        os.unlink(tmp_path)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nse_option_bhav" in inspector.get_table_names():
        bind.execute(sa.text("DELETE FROM nse_option_bhav"))
