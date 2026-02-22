from flask import Blueprint, render_template
from app.models.bias import NewsArticle
from app.models.post import Post
from app.models.comment import Comment
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func

bp = Blueprint('main', __name__)


def get_hot_posts(limit=10):
    """🔥 실시간 베스트 - Heat Score 알고리즘
    
    Heat = (likes×5 + comments×3 + views×0.1) / (hours+2)^1.2
    
    - 좋아요(능동) > 댓글(참여) > 조회(수동)
    - 시간 감쇠로 최신 인기글 우선
    - 48시간 이내 글만 대상
    """
    cutoff = datetime.utcnow() - timedelta(hours=48)
    
    posts = Post.query.filter(
        Post.created_at >= cutoff,
        Post.board_type != 'notice'
    ).all()
    
    scored = []
    now = datetime.utcnow()
    for post in posts:
        hours = (now - post.created_at).total_seconds() / 3600
        likes = post.likes_count
        comments = post.comments_count
        views = post.views or 0
        
        score = (likes * 5 + comments * 3 + views * 0.1) / ((hours + 2) ** 1.2)
        
        if score > 0:
            scored.append((post, score))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item[0] for item in scored[:limit]]


@bp.route('/')
def index():
    """메인 페이지"""
    hot_posts = get_hot_posts(10)
    try:
        articles = NewsArticle.query.order_by(NewsArticle.created_at.desc()).limit(5).all()
    except Exception:
        articles = []
    return render_template('main/index.html', hot_posts=hot_posts, articles=articles)


@bp.route('/about')
def about():
    """소개 페이지"""
    return render_template('main/about.html')


@bp.route('/policy')
def policy():
    return render_template('policy.html')
