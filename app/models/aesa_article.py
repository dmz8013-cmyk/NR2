from datetime import datetime
from app import db

class AesaArticle(db.Model):
    __tablename__ = 'aesa_articles'

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(db.Text, nullable=True)
    lenses = db.Column(db.String(50), nullable=True)  # e.g. "A,B,D"
    korea_investment_link = db.Column(db.Boolean, default=False)
    korea_insight = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='pending')
    # status: pending, sent_urgent, queued_batch, sent_batch,
    #         queued_for_morning, sent_night (구: 'sent'), queued_for_summary, sent_summary
    created_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f'<AesaArticle {self.source} - Score: {self.score}>'
