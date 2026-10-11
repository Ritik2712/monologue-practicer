"""feedback summary: the notes the AI model last picked out as the most telling

Revision ID: 5c2a9e7b1d43
Revises: 3b8e6d1f4a27
Create Date: 2026-10-11 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2a9e7b1d43'
down_revision: Union[str, Sequence[str], None] = '3b8e6d1f4a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'feedback_summary',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('model_seconds', sa.Float(), nullable=True),
        sa.Column('note_count', sa.Integer(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('picked', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('feedback_summary')
