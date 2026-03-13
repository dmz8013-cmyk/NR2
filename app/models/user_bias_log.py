"""사용자 기사 클릭 편향 로그 모델"""
from datetime import datetime
from app import db


class UserBiasLog(db.Model):
    __tablename__ = 'user_bias_log'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    article_id = db.Column(db.Integer, nullable=False)
    source_political = db.Column(db.Float, nullable=True)
    source_geopolitical = db.Column(db.Float, nullable=True)
    source_economic = db.Column(db.Float, nullable=True)
    clicked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
