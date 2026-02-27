"""Add user_id, confidence, risk_tier columns to fraud_scores table.

Revision ID: 001
Revises:
Create Date: 2026-02-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fraud_scores",
        sa.Column("user_id", sa.String(), nullable=True),
    )
    op.add_column(
        "fraud_scores",
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "fraud_scores",
        sa.Column("risk_tier", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_fraud_scores_user_id"),
        "fraud_scores",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_fraud_scores_user_id"), table_name="fraud_scores")
    op.drop_column("fraud_scores", "risk_tier")
    op.drop_column("fraud_scores", "confidence")
    op.drop_column("fraud_scores", "user_id")
