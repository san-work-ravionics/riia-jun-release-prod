"""seed shared demo user (webmaster@ravionics.nl)

Revision ID: 20260611_seed_demo_user
Revises: 20260603_add_user_hedge_plans
Create Date: 2026-06-11 10:00:00.000000

Seeds the shared demo account used by the dashboard "Demo" auth mode. The user
authenticates via /auth/token like any other user; it is granted all access
flags so the demo can exercise every function (portfolio, research, ops).
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260611_seed_demo_user"
down_revision: Union[str, Sequence[str], None] = "20260603_add_user_hedge_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEMO_USER_ID = "webmaster@ravionics.nl"


def upgrade() -> None:
    bind = op.get_bind()
    # The `users` table is created by Base.metadata.create_all() at app startup,
    # not by a migration. In CI the migration chain runs against a fresh DB with
    # no create_all(), so the table is absent — skip seeding there (matches the
    # try/except guards in the other user-touching migrations).
    if "users" not in sa.inspect(bind).get_table_names():
        return

    existing = bind.execute(
        sa.text("SELECT id FROM users WHERE id = :id"), {"id": DEMO_USER_ID}
    ).first()
    if existing is None:
        op.execute(
            sa.text(
                "INSERT INTO users "
                "(id, can_assist_research, can_create_portfolio, can_review_portfolio, can_access_ops) "
                "VALUES (:id, 1, 1, 1, 1)"
            ).bindparams(id=DEMO_USER_ID)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "users" not in sa.inspect(bind).get_table_names():
        return
    op.execute(
        sa.text("DELETE FROM users WHERE id = :id").bindparams(id=DEMO_USER_ID)
    )
