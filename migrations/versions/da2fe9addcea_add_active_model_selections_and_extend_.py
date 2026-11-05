"""add_active_model_selections_and_extend_model_config

Revision ID: da2fe9addcea
Revises: 9a0_email_settings_and_payload
"""
from alembic import op
import sqlalchemy as sa

revision = 'da2fe9addcea'
down_revision = '9a0_email_settings_and_payload'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create active_model_selections table
    op.create_table(
        'active_model_selections',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('role', sa.String(length=80), nullable=False),
        sa.Column('provider', sa.String(length=80), nullable=False),
        sa.Column('selected_model', sa.String(length=200), nullable=False),
        sa.Column('validated', sa.Boolean(), nullable=False),
        sa.Column('validation_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role', name='uq_active_model_role')
    )
    op.create_index(op.f('ix_active_model_selections_role'), 'active_model_selections', ['role'], unique=False)
    
    # Extend model_configurations table
    with op.batch_alter_table('model_configurations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_type', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('context_length', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('parameter_count', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('quantization', sa.String(length=40), nullable=True))


def downgrade() -> None:
    # Remove extensions from model_configurations
    with op.batch_alter_table('model_configurations', schema=None) as batch_op:
        batch_op.drop_column('quantization')
        batch_op.drop_column('parameter_count')
        batch_op.drop_column('context_length')
        batch_op.drop_column('model_type')
    
    # Drop active_model_selections table
    op.drop_index(op.f('ix_active_model_selections_role'), table_name='active_model_selections')
    op.drop_table('active_model_selections')
