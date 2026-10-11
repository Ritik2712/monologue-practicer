"""references and waveforms: a role and title for recordings, and a stored waveform outline

Revision ID: 9a3f1c7d2e58
Revises: 7c1e5a2b9d43
Create Date: 2026-10-11 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a3f1c7d2e58'
down_revision: Union[str, Sequence[str], None] = '7c1e5a2b9d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Everything stored so far is one of the user's own takes.
    op.add_column('jobs', sa.Column('role', sa.String(length=16), server_default='take', nullable=False))
    op.add_column('jobs', sa.Column('title', sa.String(length=120), nullable=True))
    op.add_column('analyses', sa.Column('role', sa.String(length=16), server_default='take', nullable=False))
    op.add_column('analyses', sa.Column('title', sa.String(length=120), nullable=True))
    op.add_column('analyses', sa.Column('waveform', sa.JSON(), nullable=True))
    op.create_index(op.f('ix_analyses_role'), 'analyses', ['role'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_analyses_role'), table_name='analyses')
    op.drop_column('analyses', 'waveform')
    op.drop_column('analyses', 'title')
    op.drop_column('analyses', 'role')
    op.drop_column('jobs', 'title')
    op.drop_column('jobs', 'role')
