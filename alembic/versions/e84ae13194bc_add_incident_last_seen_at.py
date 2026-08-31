"""add incident last_seen_at

Revision ID: e84ae13194bc
Revises: 05309b1bea50
Create Date: 2026-08-31 10:46:14.909663

"""
from alembic import op
import sqlalchemy as sa


revision = 'e84ae13194bc'
down_revision = '05309b1bea50'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add as nullable first, backfill existing rows, then enforce NOT
    # NULL -- an unconditional NOT NULL add fails against any DB that
    # already has incident rows (which any real deployment will).
    # Backfill uses started_at as the best available approximation of
    # "last touched" for pre-existing rows; every row created after this
    # migration gets a real last_seen_at from the model default going
    # forward.
    op.add_column('incidents', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))
    op.execute('UPDATE incidents SET last_seen_at = started_at WHERE last_seen_at IS NULL')
    op.alter_column('incidents', 'last_seen_at', nullable=False)


def downgrade() -> None:
    op.drop_column('incidents', 'last_seen_at')