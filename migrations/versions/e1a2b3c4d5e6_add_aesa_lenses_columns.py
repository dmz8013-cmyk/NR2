"""add lenses and korea_investment_link to aesa_articles

Revision ID: e1a2b3c4d5e6
Revises: d4e5f6a7b8c9
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1a2b3c4d5e6'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('aesa_articles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lenses', sa.String(50), nullable=True))
        batch_op.add_column(sa.Column('korea_investment_link', sa.Boolean(), server_default='false', nullable=True))


def downgrade():
    with op.batch_alter_table('aesa_articles', schema=None) as batch_op:
        batch_op.drop_column('korea_investment_link')
        batch_op.drop_column('lenses')
