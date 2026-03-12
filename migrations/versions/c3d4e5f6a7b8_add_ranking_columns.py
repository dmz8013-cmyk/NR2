"""add ranking columns to news_articles

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('news_articles', sa.Column('is_ranking', sa.Boolean(), server_default='false'))
    op.add_column('news_articles', sa.Column('ranking_section', sa.String(20), nullable=True))
    op.add_column('news_articles', sa.Column('ranking_rank', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('news_articles', 'ranking_rank')
    op.drop_column('news_articles', 'ranking_section')
    op.drop_column('news_articles', 'is_ranking')
