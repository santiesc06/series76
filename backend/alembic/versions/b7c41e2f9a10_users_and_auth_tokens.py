"""users and auth tokens; sessions.user_id becomes a foreign key (US-21, design U1-U3)

Revision ID: b7c41e2f9a10
Revises: 5deea6a805a4
Create Date: 2026-11-08 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c41e2f9a10"
down_revision: str | Sequence[str] | None = "5deea6a805a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(op.f("ix_auth_tokens_user_id"), "auth_tokens", ["user_id"], unique=False)

    # Conversations created before login have no owner (NULL); any other value cannot be a user.
    op.execute(
        "UPDATE sessions SET user_id = NULL WHERE user_id IS NOT NULL "
        "AND user_id !~ '^[0-9a-fA-F-]{36}$'"
    )
    op.alter_column(
        "sessions",
        "user_id",
        existing_type=sa.String(length=64),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        postgresql_using="user_id::uuid",
    )
    op.create_foreign_key(
        "sessions_user_id_fkey", "sessions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint("sessions_user_id_fkey", "sessions", type_="foreignkey")
    op.alter_column(
        "sessions",
        "user_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=64),
        existing_nullable=True,
        postgresql_using="user_id::text",
    )
    op.drop_index(op.f("ix_auth_tokens_user_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("users")
