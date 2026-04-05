from datetime import datetime
from app import db

class AesaArticle(db.Model):
    __tablename__ = 'aesa_articles'

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(db.Text, nullable=True) # 1-line Korean angle summary
    status = db.Column(db.String(20), default='pending') # 'pending', 'sent', 'queued_for_morning', 'queued_for_summary'
    created_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f'<AesaArticle {self.source} - Score: {self.score}>'
