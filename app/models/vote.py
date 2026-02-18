from datetime import datetime
from app import db

class Vote(db.Model):
    __tablename__ = 'votes'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    is_multiple = db.Column(db.Boolean, default=False)  # 복수 선택 가능 여부
    end_date = db.Column(db.DateTime, nullable=True)  # 투표 종료일
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    options = db.relationship('VoteOption', backref='vote', lazy='dynamic', cascade='all, delete-orphan')
    responses = db.relationship('VoteResponse', backref='vote', lazy='dynamic', cascade='all, delete-orphan')
    creator = db.relationship('User', backref='votes')

    @property
    def total_votes(self):
        """전체 투표 수"""
        return self.responses.count()

    @property
    def is_active(self):
        """투표가 활성화되어 있는지 확인"""
        if self.end_date is None:
            return True
        return datetime.utcnow() < self.end_date

    def __repr__(self):
        return f'<Vote {self.title}>'


class VoteOption(db.Model):
    __tablename__ = 'vote_options'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)

    # Foreign Keys
    vote_id = db.Column(db.Integer, db.ForeignKey('votes.id'), nullable=False)

    # Relationships
    responses = db.relationship('VoteResponse', backref='option', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def votes_count(self):
        """이 옵션에 투표한 수"""
        return self.responses.count()

    @property
    def percentage(self):
        """전체 투표에서 이 옵션의 비율"""
        total = self.vote.total_votes
        if total == 0:
            return 0
        return (self.votes_count / total) * 100

    def __repr__(self):
        return f'<VoteOption {self.text}>'


class VoteResponse(db.Model):
    __tablename__ = 'vote_responses'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vote_id = db.Column(db.Integer, db.ForeignKey('votes.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('vote_options.id'), nullable=False)

    # Unique constraint to prevent duplicate votes (unless multiple choice)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'vote_id', 'option_id', name='unique_user_vote_option'),
    )

    def __repr__(self):
        return f'<VoteResponse user_id={self.user_id} option_id={self.option_id}>'
