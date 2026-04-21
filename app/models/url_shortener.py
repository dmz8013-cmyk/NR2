from datetime import datetime
from app import db


class URLShortener(db.Model):
    __tablename__ = 'url_shortener'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    original_url = db.Column(db.Text, nullable=False)
    title = db.Column(db.String(300), nullable=True)
    domain = db.Column(db.String(100), nullable=True)
    press_name = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    click_count = db.Column(db.Integer, default=0, nullable=False)
    last_clicked_at = db.Column(db.DateTime, nullable=True)
    source_bot = db.Column(db.String(30), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    custom_code = db.Column(db.Boolean, default=False, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False)

    clicks = db.relationship(
        'URLClickLog',
        backref='shortener',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<URLShortener {self.code} → {(self.original_url or "")[:40]}>'


class URLClickLog(db.Model):
    __tablename__ = 'url_click_log'

    id = db.Column(db.Integer, primary_key=True)
    shortener_id = db.Column(
        db.Integer,
        db.ForeignKey('url_shortener.id', ondelete='CASCADE'),
        nullable=False,
    )
    clicked_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    user_agent = db.Column(db.Text, nullable=True)
    ip_hash = db.Column(db.String(64), nullable=True)
    referer = db.Column(db.Text, nullable=True)
    device_type = db.Column(db.String(20), nullable=True)

    def __repr__(self):
        return f'<URLClickLog shortener={self.shortener_id} at={self.clicked_at}>'
