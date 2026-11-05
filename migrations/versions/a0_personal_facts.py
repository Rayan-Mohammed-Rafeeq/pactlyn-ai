"""add personal_facts table for structured personal memory

Revision ID: a0_personal_facts
Revises: 9a0_email_settings_and_payload
"""

import sqlalchemy as sa
from alembic import op

revision = "a0_personal_facts"
down_revision = "9a0_email_settings_and_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_facts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "identity",
                "birthday",
                "education",
                "career",
                "preference",
                "contact_information",
                "personal_relationship",
                "other",
                name="personalfactcategory",
            ),
            nullable=False,
        ),
        sa.Column("attribute", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("recurrence", sa.String(length=40), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmation_state",
            sa.Enum(
                "confirmed",
                "needs_confirmation",
                "contradicted",
                name="personalfactconfirmationstate",
            ),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("indexed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category", "attribute", name="uq_personal_fact_attribute"),
    )
    op.create_index("ix_personal_facts_category", "personal_facts", ["category"])

    # FTS5 virtual table for keyword lookup over personal facts.
    # op.execute cannot be used for CREATE VIRTUAL TABLE on all Alembic backends,
    # so we use the raw connection.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS personal_fact_fts USING fts5("
            "fact_id UNINDEXED, attribute, value, display_value, source_text)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS personal_fact_fts"))
    op.drop_index("ix_personal_facts_category", table_name="personal_facts")
    op.drop_table("personal_facts")
