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
    op.execute(
        sa.text("DELETE FROM users WHERE id = :id").bindparams(id=DEMO_USER_ID)
    )
