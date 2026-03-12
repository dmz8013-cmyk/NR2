"""add article_clusters table and cluster_id FK

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('article_clusters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.add_column('news_articles', sa.Column('cluster_id', sa.Integer(), sa.ForeignKey('article_clusters.id'), nullable=True))


def downgrade():
    op.drop_column('news_articles', 'cluster_id')
    op.drop_table('article_clusters')
