"""persist relationship evidence and rejected-edge audit records

Revision ID: 8c0_relationship_review_audit
Revises: 7b0_event_intermediate_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "8c0_relationship_review_audit"
down_revision = "7b0_event_intermediate_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commitment_relationships", sa.Column("evidence", sa.Text(), nullable=False, server_default=""))
    op.add_column("commitment_relationships", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("commitment_relationships", sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="validated"))
    op.create_table(
        "commitment_relationship_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_commitment_id", sa.String(length=36), nullable=True),
        sa.Column("target_commitment_id", sa.String(length=36), nullable=True),
        sa.Column("source_index", sa.Integer(), nullable=True),
        sa.Column("target_index", sa.Integer(), nullable=True),
        sa.Column("source_event_id", sa.String(length=80), nullable=True),
        sa.Column("target_event_id", sa.String(length=80), nullable=True),
        sa.Column("relationship", sa.String(length=80), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_commitment_id"], ["commitments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_commitment_id"], ["commitments.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_commitment_relationship_reviews_source_commitment_id", "commitment_relationship_reviews", ["source_commitment_id"])
    op.create_index("ix_commitment_relationship_reviews_target_commitment_id", "commitment_relationship_reviews", ["target_commitment_id"])


def downgrade() -> None:
    op.drop_index("ix_commitment_relationship_reviews_target_commitment_id", table_name="commitment_relationship_reviews")
    op.drop_index("ix_commitment_relationship_reviews_source_commitment_id", table_name="commitment_relationship_reviews")
    op.drop_table("commitment_relationship_reviews")
    op.drop_column("commitment_relationships", "validation_status")
    op.drop_column("commitment_relationships", "confidence")
    op.drop_column("commitment_relationships", "evidence")
