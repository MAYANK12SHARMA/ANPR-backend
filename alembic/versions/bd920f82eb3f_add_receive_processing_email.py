"""add receive_processing_email

Revision ID: bd920f82eb3f
Revises: 27708352d998
Create Date: 2026-07-31 22:58:09.174834

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "bd920f82eb3f"
down_revision: Union[str, Sequence[str], None] = "27708352d998"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove old subscriber table
    op.drop_index(
        op.f("ix_email_subscribers_email"),
        table_name="email_subscribers",
    )

    op.drop_index(
        op.f("ix_email_subscribers_id"),
        table_name="email_subscribers",
    )

    op.drop_table("email_subscribers")

    # Add new column with default=True
    op.add_column(
        "users",
        sa.Column(
            "receive_processing_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Remove default for future inserts
    op.alter_column(
        "users",
        "receive_processing_email",
        server_default=None,
    )


def downgrade() -> None:

    op.drop_column(
        "users",
        "receive_processing_email",
    )

    op.create_table(
        "email_subscribers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "ADMIN",
                "OPERATOR",
                "VIEWER",
                name="email_role",
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_index(
        "ix_email_subscribers_email",
        "email_subscribers",
        ["email"],
        unique=True,
    )

    op.create_index(
        "ix_email_subscribers_id",
        "email_subscribers",
        ["id"],
    )
