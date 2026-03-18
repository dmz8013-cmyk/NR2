from datetime import datetime
from app import db

class Post(db.Model):
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    board_type = db.Column(db.String(20), nullable=False)  # 'free', 'left', 'right', 'fakenews', 'aesa'
    youtube_url = db.Column(db.String(500), nullable=True)
    youtube_video_id = db.Column(db.String(20), nullable=True, unique=True, index=True)
    external_url = db.Column(db.String(500), nullable=True)   # 누렁이 픽: 외부 링크
    og_image = db.Column(db.String(500), nullable=True)       # 누렁이 픽: OG 이미지 URL
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Foreign Keys
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Relationships
    images = db.relationship('PostImage', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    post_votes = db.relationship('PostVote', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def likes_count(self):
        """좋아요 개수"""
        return self.likes.count()

    @property
    def comments_count(self):
        """댓글 개수 (대댓글 포함)"""
        return self.comments.count()

    @property
    def shorts_video_id(self):
        """유튜브 쇼츠/일반 URL에서 VIDEO_ID 추출"""
        if not self.external_url:
            return None
        import re
        # youtube.com/shorts/{ID}
        m = re.search(r'youtube\.com/shorts/([a-zA-Z0-9_-]{11})', self.external_url)
        if m:
            return m.group(1)
        # youtu.be/{ID}
        m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', self.external_url)
        if m:
            return m.group(1)
        # youtube.com/watch?v={ID}
        m = re.search(r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})', self.external_url)
        if m:
            return m.group(1)
        return None

    @property
    def external_domain(self):
        """외부 링크 도메인 추출"""
        if not self.external_url:
            return ''
        try:
            from urllib.parse import urlparse
            return urlparse(self.external_url).netloc.replace('www.', '')
        except Exception:
            return ''

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
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Foreign Keys
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)

    def __repr__(self):
        return f'<PostImage {self.filename}>'
