"""coaching: job kind, stored coaching, and the worker's view of the language model

Revision ID: 7c1e5a2b9d43
Revises: 04a480e7bbb1
Create Date: 2026-10-11 12:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e5a2b9d43'
down_revision: Union[str, Sequence[str], None] = '04a480e7bbb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing jobs all measured a recording, so they become kind "analysis".
    op.add_column('jobs', sa.Column('kind', sa.String(length=16), server_default='analysis', nullable=False))
    op.add_column('analyses', sa.Column('coaching', sa.JSON(), nullable=True))
    op.add_column('worker_state', sa.Column('coach_model', sa.String(length=64), nullable=True))
    op.add_column('worker_state', sa.Column('coach_status', sa.String(length=32), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('worker_state', 'coach_status')
    op.drop_column('worker_state', 'coach_model')
    op.drop_column('analyses', 'coaching')
    op.drop_column('jobs', 'kind')
