"""add_processing_tasks_table

Revision ID: c42ba984dffb
Revises: 08d397ecb050
"""
from alembic import op
import sqlalchemy as sa

revision = 'c42ba984dffb'
down_revision = '08d397ecb050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create processing_tasks table
    op.create_table('processing_tasks',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('task_type', sa.String(), nullable=False),
    sa.Column('document_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('input_data', sa.JSON(), nullable=False),
    sa.Column('output_data', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processing_tasks_created_at'), 'processing_tasks', ['created_at'], unique=False)
    op.create_index(op.f('ix_processing_tasks_document_id'), 'processing_tasks', ['document_id'], unique=False)
    op.create_index(op.f('ix_processing_tasks_status'), 'processing_tasks', ['status'], unique=False)
    op.create_index(op.f('ix_processing_tasks_task_type'), 'processing_tasks', ['task_type'], unique=False)
    op.create_index('ix_tasks_status_priority', 'processing_tasks', ['status', 'priority'], unique=False)


def downgrade() -> None:
    # Drop processing_tasks table
    op.drop_index('ix_tasks_status_priority', table_name='processing_tasks')
    op.drop_index(op.f('ix_processing_tasks_task_type'), table_name='processing_tasks')
    op.drop_index(op.f('ix_processing_tasks_status'), table_name='processing_tasks')
    op.drop_index(op.f('ix_processing_tasks_document_id'), table_name='processing_tasks')
    op.drop_index(op.f('ix_processing_tasks_created_at'), table_name='processing_tasks')
    op.drop_table('processing_tasks')
