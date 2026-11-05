"""persist email settings metadata and exact-payload fields

Revision ID: 9a0_email_settings_and_payload
Revises: 8c0_relationship_review_audit
"""

import sqlalchemy as sa
from alembic import op

revision = "9a0_email_settings_and_payload"
down_revision = "8c0_relationship_review_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_accounts",
        sa.Column("sender_name", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "email_accounts",
        sa.Column(
            "sync_interval_minutes", sa.Integer(), nullable=False, server_default="15"
        ),
    )
    op.add_column(
        "email_accounts",
        sa.Column("last_test_status", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "email_accounts",
        sa.Column("last_test_detail", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "email_accounts",
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "email_messages",
        sa.Column("references_header", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "email_send_actions",
        sa.Column("headers", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "email_send_actions",
        sa.Column(
            "attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
    )


def downgrade() -> None:
    op.drop_column("email_send_actions", "attachments")
    op.drop_column("email_send_actions", "headers")
    op.drop_column("email_messages", "references_header")
    op.drop_column("email_accounts", "last_tested_at")
    op.drop_column("email_accounts", "last_test_detail")
    op.drop_column("email_accounts", "last_test_status")
    op.drop_column("email_accounts", "sync_interval_minutes")
    op.drop_column("email_accounts", "sender_name")
