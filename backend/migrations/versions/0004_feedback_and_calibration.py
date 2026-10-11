"""feedback and calibration: stored feedback, versions of the adjustable settings, revisions

Revision ID: 3b8e6d1f4a27
Revises: 9a3f1c7d2e58
Create Date: 2026-10-11 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b8e6d1f4a27'
down_revision: Union[str, Sequence[str], None] = '9a3f1c7d2e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'calibration_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('adaptive_enabled', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'calibration_versions',
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('cause', sa.String(length=16), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('setting', sa.String(length=48), nullable=True),
        sa.Column('old_value', sa.Float(), nullable=True),
        sa.Column('new_value', sa.Float(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('report_count', sa.Integer(), nullable=False),
        sa.Column('agreeing_count', sa.Integer(), nullable=False),
        sa.Column('recording_count', sa.Integer(), nullable=False),
        sa.Column('undone_by', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('version'),
    )
    op.create_table(
        'feedback',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('analysis_id', sa.String(length=32), nullable=False),
        sa.Column('recording_id', sa.String(length=32), nullable=False),
        sa.Column('slot', sa.String(length=64), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('target_kind', sa.String(length=16), nullable=False),
        sa.Column('target_id', sa.String(length=32), nullable=True),
        sa.Column('at_seconds', sa.Float(), nullable=True),
        sa.Column('note', sa.String(length=280), nullable=True),
        sa.Column('calibration_version', sa.Integer(), nullable=False),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('setting', sa.String(length=48), nullable=True),
        sa.Column('direction', sa.Integer(), nullable=False),
        sa.Column('evidence', sa.Float(), nullable=True),
        sa.Column('used_by_version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('analysis_id', 'slot', name='uq_feedback_slot'),
    )
    op.create_index(op.f('ix_feedback_analysis_id'), 'feedback', ['analysis_id'], unique=False)
    op.create_index(op.f('ix_feedback_setting'), 'feedback', ['setting'], unique=False)

    op.add_column('jobs', sa.Column('source_analysis_id', sa.String(length=32), nullable=True))
    # Everything stored so far was analysed with the default settings: calibration version 1.
    op.add_column('analyses', sa.Column('calibration_version', sa.Integer(), server_default='1', nullable=False))
    op.add_column('analyses', sa.Column('root_id', sa.String(length=32), nullable=True))
    op.add_column('analyses', sa.Column('revision_reason', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_analyses_root_id'), 'analyses', ['root_id'], unique=False)
    # Every existing result is the first and only result of its recording.
    op.execute("UPDATE analyses SET root_id = id")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_analyses_root_id'), table_name='analyses')
    op.drop_column('analyses', 'revision_reason')
    op.drop_column('analyses', 'root_id')
    op.drop_column('analyses', 'calibration_version')
    op.drop_column('jobs', 'source_analysis_id')
    op.drop_index(op.f('ix_feedback_setting'), table_name='feedback')
    op.drop_index(op.f('ix_feedback_analysis_id'), table_name='feedback')
    op.drop_table('feedback')
    op.drop_table('calibration_versions')
    op.drop_table('calibration_state')
