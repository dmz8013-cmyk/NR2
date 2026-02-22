from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    profile_image = db.Column(db.String(255), default='default_profile.jpeg')
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # === 인증 시스템 ===
    verify_tier = db.Column(db.String(20), default='bronze')  # bronze, silver, gold, diamond
    verify_category = db.Column(db.String(30), nullable=True)  # 직업 카테고리
    # 카테고리: congress(국회), government(정부), public_org(공공기관),
    #          local_gov(지자체), party(정당), media(언론), pr(홍보대관),
    #          research(연구학계), legal(법조), citizen(시민)
    verify_badge = db.Column(db.String(50), nullable=True)  # 표시용 뱃지 텍스트
    verified_at = db.Column(db.DateTime, nullable=True)

    # === 뼈다귀 포인트 ===
    bones = db.Column(db.Float, default=0.0)
    total_bias_votes = db.Column(db.Integer, default=0)
    accurate_votes = db.Column(db.Integer, default=0)

    # Relationships
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    vote_responses = db.relationship('VoteResponse', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    events = db.relationship('Event', backref='creator', lazy='dynamic', cascade='all, delete-orphan')
    bias_votes = db.relationship('BiasVote', backref='voter', lazy='dynamic', cascade='all, delete-orphan')
    bone_transactions = db.relationship('BoneTransaction', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    submitted_articles = db.relationship('NewsArticle', backref='submitter', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def vote_weight(self):
        weights = {'bronze': 0, 'silver': 1.0, 'gold': 1.5, 'diamond': 2.0}
        return weights.get(self.verify_tier, 0)

    @property
    def accuracy_rate(self):
        if self.total_bias_votes == 0:
            return 0
        return round(self.accurate_votes / self.total_bias_votes * 100)

    def add_bones(self, amount, reason):
        from app.models.bias import BoneTransaction
        self.bones += amount
        txn = BoneTransaction(user_id=self.id, amount=amount, reason=reason)
        db.session.add(txn)

    def set_password(self, password):
        """비밀번호를 해시화하여 저장"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """비밀번호 확인"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.nickname}>'
