from flask import Blueprint, render_template
from app.models.bias import NewsArticle
from app.models.briefing import Briefing
from app.models.post import Post
from app.models.comment import Comment
from app import db
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import Blueprint, render_template, make_response, request

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
    try:
        latest_briefings = Briefing.query.order_by(Briefing.created_at.desc()).limit(4).all()
    except Exception:
        latest_briefings = []
    return render_template('main/index.html', hot_posts=hot_posts, articles=articles, latest_briefings=latest_briefings)


@bp.route('/about')
def about():
    """소개 페이지"""
    return render_template('main/about.html')


@bp.route('/policy')
def policy():
    return render_template('policy.html')
@bp.route('/robots.txt')
def robots():
    content = """User-agent: *
Allow: /
Allow: /briefings
Allow: /boards/
Disallow: /admin/
Disallow: /api/

Sitemap: https://nr2.kr/sitemap.xml
"""
    resp = make_response(content)
    resp.headers['Content-Type'] = 'text/plain'
    return resp


@bp.route('/sitemap.xml')
def sitemap():
    pages = []
    # 고정 페이지
    pages.append({'loc': 'https://nr2.kr/', 'priority': '1.0', 'changefreq': 'daily'})
    pages.append({'loc': 'https://nr2.kr/briefings', 'priority': '0.9', 'changefreq': 'daily'})
    pages.append({'loc': 'https://nr2.kr/boards/free', 'priority': '0.7', 'changefreq': 'daily'})
    pages.append({'loc': 'https://nr2.kr/boards/news', 'priority': '0.7', 'changefreq': 'daily'})
    pages.append({'loc': 'https://nr2.kr/boards/bias', 'priority': '0.8', 'changefreq': 'daily'})

    # 브리핑 개별 페이지
    try:
        briefings = Briefing.query.order_by(Briefing.created_at.desc()).limit(100).all()
        for b in briefings:
            pages.append({
                'loc': f'https://nr2.kr/briefings/{b.id}',
                'priority': '0.8',
                'changefreq': 'weekly',
                'lastmod': b.created_at.strftime('%Y-%m-%d')
            })
    except:
        pass

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for p in pages:
        xml += '  <url>\n'
        xml += f'    <loc>{p["loc"]}</loc>\n'
        if p.get('lastmod'):
            xml += f'    <lastmod>{p["lastmod"]}</lastmod>\n'
        xml += f'    <changefreq>{p["changefreq"]}</changefreq>\n'
        xml += f'    <priority>{p["priority"]}</priority>\n'
        xml += '  </url>\n'
    xml += '</urlset>'

    resp = make_response(xml)
    resp.headers['Content-Type'] = 'application/xml'
    return resp