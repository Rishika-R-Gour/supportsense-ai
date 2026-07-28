"""add ticket ownership and assignment

Revision ID: c48f6c5a7d11
Revises: ba9ca98cc5cb
Create Date: 2026-07-28 00:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c48f6c5a7d11"
down_revision: Union[str, Sequence[str], None] = "ba9ca98cc5cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column("requester_subject", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_tickets_requester_subject"),
        "tickets",
        ["requester_subject"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tickets_assigned_to"),
        "tickets",
        ["assigned_to"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_tickets_assigned_to"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_requester_subject"), table_name="tickets")
    op.drop_column("tickets", "assigned_to")
    op.drop_column("tickets", "requester_subject")
