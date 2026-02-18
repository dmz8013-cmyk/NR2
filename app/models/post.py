from datetime import datetime
from app import db

class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    board_type = db.Column(db.String(20), nullable=False)  # 'free', 'left', 'right', 'fakenews', 'aesa'
    youtube_url = db.Column(db.String(500), nullable=True)
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    images = db.relationship('PostImage', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def likes_count(self):
        """좋아요 개수"""
        return self.likes.count()

    @property
    def comments_count(self):
        """댓글 개수 (대댓글 포함)"""
        return self.comments.count()

    def increment_views(self):
        """조회수 증가"""
        self.views += 1
        db.session.commit()

    def __repr__(self):
        return f'<Post {self.title}>'


class PostImage(db.Model):
    __tablename__ = 'post_images'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    order = db.Column(db.Integer, default=0)  # 이미지 순서
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign Keys
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)

    def __repr__(self):
        return f'<PostImage {self.filename}>'
