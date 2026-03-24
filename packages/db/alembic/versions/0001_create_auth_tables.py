"""create auth tables (users, sessions, user_repos)

Revision ID: 0001
Revises:
Create Date: 2026-03-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigger function to auto-update updated_at on row modification
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id", name="uq_users_github_id"),
    )

    op.execute("""
        CREATE TRIGGER trg_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("github_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])
    op.create_index("idx_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "user_repos",
        sa.Column("id", sa.String(), nullable=False, server_default=sa.text("gen_random_uuid()::text")),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("repo_url", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False, server_default="main"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_repos_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "repo_id", name="uq_user_repos_user_repo"),
    )
    op.create_index("idx_user_repos_user_id", "user_repos", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_user_repos_user_id", table_name="user_repos")
    op.drop_table("user_repos")
    op.drop_index("idx_sessions_expires_at", table_name="sessions")
    op.drop_index("idx_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users")
    op.drop_table("users")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
