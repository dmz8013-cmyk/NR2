from datetime import datetime
from app import db

class PostVote(db.Model):
    __tablename__ = 'post_votes'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  # 'up' or 'down'
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('post_id', 'user_id', name='unique_post_vote'),
    )

    def __repr__(self):
        return f'<PostVote user_id={self.user_id} post_id={self.post_id} type={self.vote_type}>'
