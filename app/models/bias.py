"""뉴스 편향 투표 시스템 모델"""
import json
import os
from datetime import datetime
from app import db


def get_media_bias(source_name):
    """언론사 이름으로 korean_media_bias.json에서 성향 점수를 조회한다.
    Returns: dict with keys political, geopolitical, economic (or all None)
    """
    result = {'political': None, 'geopolitical': None, 'economic': None}
    if not source_name:
        return result

    data_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'korean_media_bias.json')
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return result

    name = source_name.strip()
    for m in data.get('media', []):
        if name in (m.get('name'), m.get('short'), m.get('id')):
            return {
                'political': m.get('political'),
                'geopolitical': m.get('geopolitical'),
                'economic': m.get('economic'),
            }
    return result


class NewsArticle(db.Model):
    __tablename__ = 'news_articles'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    url = db.Column(db.String(500), nullable=False, unique=True)
    source = db.Column(db.String(100), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    source_political = db.Column(db.Float, nullable=True)      # 언론사 정치축 -100~100
    source_geopolitical = db.Column(db.Float, nullable=True)   # 언론사 지정학축 -100~100
    source_economic = db.Column(db.Float, nullable=True)       # 언론사 경제축 -100~100

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
        total = self.vote_total or 0
        return round((self.vote_left or 0) / total * 100) if total > 0 else 0

    @property
    def center_pct(self):
        total = self.vote_total or 0
        return round((self.vote_center or 0) / total * 100) if total > 0 else 0

    @property
    def right_pct(self):
        total = self.vote_total or 0
        return round((self.vote_right or 0) / total * 100) if total > 0 else 0

    @property
    def bias_label(self):
        if (self.vote_total or 0) < 10:
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
