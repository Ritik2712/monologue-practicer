"""monologue takes: which monologue a take was recorded for

Revision ID: 7d4b2c9a6e15
Revises: 5c2a9e7b1d43
Create Date: 2026-10-11 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d4b2c9a6e15'
down_revision: Union[str, Sequence[str], None] = '5c2a9e7b1d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Empty on every existing row: a take recorded before this belongs to no monologue,
    # and stays in the General Practice history.
    op.add_column('jobs', sa.Column('monologue_id', sa.String(length=32), nullable=True))
    op.add_column('analyses', sa.Column('monologue_id', sa.String(length=32), nullable=True))
    op.create_index(op.f('ix_analyses_monologue_id'), 'analyses', ['monologue_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_analyses_monologue_id'), table_name='analyses')
    op.drop_column('analyses', 'monologue_id')
    op.drop_column('jobs', 'monologue_id')
