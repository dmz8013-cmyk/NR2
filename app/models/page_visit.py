from datetime import datetime
from app import db


class PageVisit(db.Model):
    """페이지 방문 추적 — DAU/MAU 산출용"""
    __tablename__ = 'page_visits'

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)
    path = db.Column(db.String(500), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    user_agent = db.Column(db.String(500), nullable=True)
    referrer = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<PageVisit {self.path} @ {self.created_at}>'
