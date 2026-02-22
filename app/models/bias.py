"""뉴스 편향 투표 시스템 모델"""
from datetime import datetime
from app import db


class NewsArticle(db.Model):
    __tablename__ = 'news_articles'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    url = db.Column(db.String(500), nullable=False, unique=True)
    source = db.Column(db.String(100), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    vote_left = db.Column(db.Integer, default=0)
    vote_center = db.Column(db.Integer, default=0)
    vote_right = db.Column(db.Integer, default=0)
    vote_total = db.Column(db.Integer, default=0)
    confidence = db.Column(db.Float, default=0.0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    votes = db.relationship('BiasVote', backref='article', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def left_pct(self):
        return round(self.vote_left / self.vote_total * 100) if self.vote_total > 0 else 0

    @property
    def center_pct(self):
        return round(self.vote_center / self.vote_total * 100) if self.vote_total > 0 else 0

    @property
    def right_pct(self):
        return round(self.vote_right / self.vote_total * 100) if self.vote_total > 0 else 0

    @property
    def bias_label(self):
        if self.vote_total < 10:
            return 'collecting'
        if self.left_pct >= 50:
            return 'left'
        if self.right_pct >= 50:
            return 'right'
        return 'center'

    def recalculate(self):
        votes = self.votes.all()
        left = center = right = 0
        for v in votes:
            w = v.voter.vote_weight
            if v.bias == 'left':
                left += w
            elif v.bias == 'center':
                center += w
            else:
                right += w
        total = left + center + right
        self.vote_left = round(left)
        self.vote_center = round(center)
        self.vote_right = round(right)
        self.vote_total = round(total)
        expert_count = sum(1 for v in votes if v.voter.verify_tier in ('gold', 'diamond'))
        self.confidence = min(5.0, (expert_count / max(len(votes), 1)) * 5 + (len(votes) / 50) * 2)


class BiasVote(db.Model):
    __tablename__ = 'bias_votes'

    id = db.Column(db.Integer, primary_key=True)
    bias = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_articles.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'article_id', name='unique_user_article_vote'),)


class BoneTransaction(db.Model):
    __tablename__ = 'bone_transactions'

    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
