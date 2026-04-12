"""add type parameter to upsert_memory function

Revision ID: 7a3d9c5e1b2f
Revises: 48e8c2a1f7b3
Create Date: 2026-04-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a3d9c5e1b2f"
down_revision: Union[str, Sequence[str], None] = "48e8c2a1f7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace upsert_memory function with type parameter support."""
    op.execute(
        """
        create or replace function upsert_memory(
          p_content    text,
          p_source     text,
          p_metadata   jsonb default '{}'::jsonb,
          p_session_id uuid default null,
          p_type      text default 'standard'
        )
        returns uuid
        language plpgsql
        as $$
        declare
          v_fingerprint text;
          v_id         uuid;
        begin
          v_fingerprint := encode(
            sha256(convert_to(
              lower(trim(regexp_replace(p_content, '\\s+', ' ', 'g'))),
              'UTF8'
            )),
            'hex'
          );

          insert into memories (content, source, session_id, metadata, content_fingerprint, type)
          values (p_content, p_source, p_session_id, p_metadata, v_fingerprint, p_type)
          on conflict (content_fingerprint) do update
            set updated_at = now(),
                metadata   = memories.metadata || excluded.metadata,
                type      = excluded.type
          returning id into v_id;

          return v_id;
        end;
        $$;
        """
    )


def downgrade() -> None:
    """Restore original upsert_memory without type parameter."""
    op.execute(
        """
        create or replace function upsert_memory(
          p_content    text,
          p_source     text,
          p_metadata   jsonb default '{}'::jsonb,
          p_session_id uuid default null
        )
        returns uuid
        language plpgsql
        as $$
        declare
          v_fingerprint text;
          v_id         uuid;
        begin
          v_fingerprint := encode(
            sha256(convert_to(
              lower(trim(regexp_replace(p_content, '\\s+', ' ', 'g'))),
              'UTF8'
            )),
            'hex'
          );

          insert into memories (content, source, session_id, metadata, content_fingerprint)
          values (p_content, p_source, p_session_id, p_metadata, v_fingerprint)
          on conflict (content_fingerprint) do update
            set updated_at = now(),
                metadata   = memories.metadata || excluded.metadata
          returning id into v_id;

          return v_id;
        end;
        $$;
        """
    )
