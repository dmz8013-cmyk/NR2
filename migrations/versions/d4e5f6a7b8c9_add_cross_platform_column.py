"""add is_cross_platform column to news_articles

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('news_articles', sa.Column('is_cross_platform', sa.Boolean(), server_default='false'))


def downgrade():
    op.drop_column('news_articles', 'is_cross_platform')
