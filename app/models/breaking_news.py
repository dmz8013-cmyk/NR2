from datetime import datetime
from app import db


class BreakingNews(db.Model):
    """속보 모델"""
    __tablename__ = 'breaking_news'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(100))  # 출처
    priority = db.Column(db.Integer, default=0)  # 우선순위 (높을수록 상단)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 작성자
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def __repr__(self):
        return f'<BreakingNews {self.title}>'
