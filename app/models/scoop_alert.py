from datetime import datetime
from app import db

class ScoopAlert(db.Model):
    __tablename__ = 'scoop_alerts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(1000), unique=True, nullable=False)
    source = db.Column(db.String(100), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f'<ScoopAlert {self.source}: {self.title[:20]}>'
