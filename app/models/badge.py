from datetime import datetime
from app import db

class Badge(db.Model):
    __tablename__ = 'badges'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True) # e.g. 'ATTEND_7'
    name = db.Column(db.String(100), nullable=False)                         # e.g. '7일 연속 출석'
    description = db.Column(db.String(255))                                  
    icon = db.Column(db.String(50))                                          # e.g. '🔥'
    badge_type = db.Column(db.String(20), nullable=False)                    # attendance, post, comment, np, job
    condition_value = db.Column(db.Integer, default=0)                       # 7, 10, 50 등
    created_at = db.Column(db.DateTime, default=datetime.now)

class UserBadge(db.Model):
    __tablename__ = 'user_badges'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id', ondelete='CASCADE'), nullable=False)
    is_primary = db.Column(db.Boolean, default=False)
    acquired_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (db.UniqueConstraint('user_id', 'badge_id', name='uq_user_badge'),)
    
    badge = db.relationship('Badge', backref=db.backref('user_badges', lazy='dynamic'))
