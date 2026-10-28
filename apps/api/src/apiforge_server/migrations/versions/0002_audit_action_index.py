"""audit log: index the action prefix filter

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-28 16:20:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_log_action_id",
        "audit_log",
        ["action", "id"],
        unique=False,
        postgresql_ops={"action": "varchar_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_action_id", table_name="audit_log")
