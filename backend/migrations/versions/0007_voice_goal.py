"""voice goal: whether the speaker asked to keep their voice lower or higher

Revision ID: 2f8c5a1e9b36
Revises: 7d4b2c9a6e15
Create Date: 2026-10-12 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f8c5a1e9b36'
down_revision: Union[str, Sequence[str], None] = '7d4b2c9a6e15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Every job queued so far was submitted with no goal. The goal of a finished analysis
    # is kept inside its result, so `analyses` needs no column.
    op.add_column('jobs', sa.Column('voice_goal', sa.String(length=16), server_default='none', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('jobs', 'voice_goal')
