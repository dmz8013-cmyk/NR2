"""add source bias columns to news_articles

Revision ID: c863f861fcbb
Revises: 2248f1a8c274
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c863f861fcbb'
down_revision = '2248f1a8c274'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('news_articles', sa.Column('source_political', sa.Float(), nullable=True))
    op.add_column('news_articles', sa.Column('source_geopolitical', sa.Float(), nullable=True))
    op.add_column('news_articles', sa.Column('source_economic', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('news_articles', 'source_economic')
    op.drop_column('news_articles', 'source_geopolitical')
    op.drop_column('news_articles', 'source_political')
