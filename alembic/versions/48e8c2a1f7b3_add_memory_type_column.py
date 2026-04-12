"""add memory type column

Revision ID: 48e8c2a1f7b3
Revises: 4bfa7b5e03e9
Create Date: 2026-04-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "48e8c2a1f7b3"
down_revision: Union[str, Sequence[str], None] = "4bfa7b5e03e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add type column as nullable first (existing rows will be set to 'standard' below)
    op.add_column(
        "memories",
        sa.Column("type", sa.String(), nullable=True, server_default="standard"),
    )

    # Backfill existing rows
    op.execute("UPDATE memories SET type = 'standard' WHERE type IS NULL")

    # Alter to non-nullable now that all rows have a value
    op.alter_column("memories", "type", nullable=False)

    # Add check constraint on valid memory types
    op.create_check_constraint(
        "memories_type_check",
        "memories",
        "type IN ('standard', 'identity', 'checkpoint', 'manual')",
    )

    # Index for filtering by type at query time
    op.create_index(op.f("ix_memories_type"), "memories", ["type"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_memories_type"), table_name="memories")
    op.drop_constraint("memories_type_check", "memories", type_="check")
    op.drop_column("memories", "type")
