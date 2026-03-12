"""add article AI bias columns to news_articles

Revision ID: a1b2c3d4e5f6
Revises: c863f861fcbb
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c863f861fcbb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('news_articles', sa.Column('article_political', sa.Float(), nullable=True))
    op.add_column('news_articles', sa.Column('article_geopolitical', sa.Float(), nullable=True))
    op.add_column('news_articles', sa.Column('article_economic', sa.Float(), nullable=True))
    op.add_column('news_articles', sa.Column('ai_summary', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('news_articles', 'ai_summary')
    op.drop_column('news_articles', 'article_economic')
    op.drop_column('news_articles', 'article_geopolitical')
    op.drop_column('news_articles', 'article_political')
