"""add structured event fields to commitments

Revision ID: 7b0_event_intermediate_fields
Revises: 8b5285117737
"""

import sqlalchemy as sa
from alembic import op

revision = "7b0_event_intermediate_fields"
down_revision = "8b5285117737"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("event_id", sa.String(length=80), True),
        ("actor", sa.String(length=200), True),
        ("action", sa.String(length=300), True),
        ("object", sa.String(length=300), True),
        ("beneficiary", sa.String(length=200), True),
        ("deadline_owner", sa.String(length=200), True),
        ("condition", sa.Text(), True),
        ("responsibility", sa.String(length=80), False),
        ("source_span", sa.Text(), False),
    )
    for name, column_type, nullable in columns:
        kwargs = {"nullable": nullable}
        if name == "responsibility":
            kwargs["server_default"] = "UNKNOWN"
        elif name == "source_span":
            kwargs["server_default"] = ""
        op.add_column("commitments", sa.Column(name, column_type, **kwargs))
    op.create_index("ix_commitments_event_id", "commitments", ["event_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_commitments_event_id", table_name="commitments")
    for name in ("source_span", "responsibility", "condition", "deadline_owner", "beneficiary", "object", "action", "actor", "event_id"):
        op.drop_column("commitments", name)
