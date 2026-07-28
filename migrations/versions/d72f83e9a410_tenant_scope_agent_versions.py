"""tenant scope agent versions

Revision ID: d72f83e9a410
Revises: c48f6c5a7d11
Create Date: 2026-07-28 00:15:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d72f83e9a410"
down_revision: Union[str, Sequence[str], None] = "c48f6c5a7d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_versions") as batch_op:
        batch_op.add_column(
            sa.Column("tenant_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_agent_versions_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        batch_op.create_index(
            op.f("ix_agent_versions_tenant_id"),
            ["tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_versions") as batch_op:
        batch_op.drop_index(op.f("ix_agent_versions_tenant_id"))
        batch_op.drop_constraint(
            "fk_agent_versions_tenant_id",
            type_="foreignkey",
        )
        batch_op.drop_column("tenant_id")
