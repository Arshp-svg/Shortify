"""create urls table

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "urls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("short_code", sa.String(length=32), nullable=False),
        sa.Column("original_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("click_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_urls"),
        sa.UniqueConstraint("short_code", name="uq_urls_short_code"),
    )
    op.create_index("ix_urls_short_code", "urls", ["short_code"], unique=True)
    op.create_index("ix_urls_user_id", "urls", ["user_id"], unique=False)
    op.create_index("ix_urls_active_expires_at", "urls", ["active", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_urls_active_expires_at", table_name="urls")
    op.drop_index("ix_urls_user_id", table_name="urls")
    op.drop_index("ix_urls_short_code", table_name="urls")
    op.drop_table("urls")
