"""scope agent version identity to tenant

Revision ID: e83654c19f2a
Revises: d72f83e9a410
Create Date: 2026-07-28 10:30:00
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e83654c19f2a"
down_revision: Union[str, Sequence[str], None] = "d72f83e9a410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
}


def upgrade() -> None:
    with op.batch_alter_table(
        "agent_versions",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_agent_versions_name_version",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_agent_versions_tenant_name_version",
            ["tenant_id", "name", "version"],
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "agent_versions",
        naming_convention=NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_agent_versions_tenant_name_version",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_agent_versions_name_version",
            ["name", "version"],
        )
