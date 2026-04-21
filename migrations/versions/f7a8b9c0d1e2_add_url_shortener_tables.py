"""add url_shortener and url_click_log tables

Revision ID: f7a8b9c0d1e2
Revises: e1a2b3c4d5e6
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'url_shortener',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('original_url', sa.Text(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=True),
        sa.Column('domain', sa.String(length=100), nullable=True),
        sa.Column('press_name', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('click_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_clicked_at', sa.DateTime(), nullable=True),
        sa.Column('source_bot', sa.String(length=30), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('custom_code', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('is_public', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    op.create_index('idx_shortener_code', 'url_shortener', ['code'], unique=True)
    op.create_index('idx_shortener_user', 'url_shortener', ['user_id'])
    op.create_index('idx_shortener_original', 'url_shortener', ['original_url'])

    op.create_table(
        'url_click_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('shortener_id', sa.Integer(),
                  sa.ForeignKey('url_shortener.id', ondelete='CASCADE'), nullable=False),
        sa.Column('clicked_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('referer', sa.Text(), nullable=True),
        sa.Column('device_type', sa.String(length=20), nullable=True),
    )
    op.create_index('idx_click_shortener', 'url_click_log', ['shortener_id'])
    op.create_index('idx_click_time', 'url_click_log', ['clicked_at'])
    op.create_index('idx_click_ip_hash', 'url_click_log', ['ip_hash'])


def downgrade():
    op.drop_index('idx_click_ip_hash', table_name='url_click_log')
    op.drop_index('idx_click_time', table_name='url_click_log')
    op.drop_index('idx_click_shortener', table_name='url_click_log')
    op.drop_table('url_click_log')

    op.drop_index('idx_shortener_original', table_name='url_shortener')
    op.drop_index('idx_shortener_user', table_name='url_shortener')
    op.drop_index('idx_shortener_code', table_name='url_shortener')
    op.drop_table('url_shortener')
