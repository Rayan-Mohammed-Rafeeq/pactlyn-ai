"""merge_document_and_personal_facts

Revision ID: 08d397ecb050
Revises: a0_personal_facts, b0_add_document_figures
"""
from alembic import op
import sqlalchemy as sa

revision = '08d397ecb050'
down_revision = ('a0_personal_facts', 'b0_add_document_figures')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
