"""
방문자 추적 미들웨어
app/__init__.py의 create_app()에서 init_tracking(app)을 호출하세요.
"""
from flask import request, g
from flask_login import current_user
from app import db
from app.models.page_visit import PageVisit


def init_tracking(app):
    """Flask 앱에 방문 추적 미들웨어 등록"""

    # 추적 제외 경로
    EXCLUDE_PREFIXES = (
        '/static/', '/sw.js', '/manifest.json', '/robots.txt',
        '/sitemap.xml', '/favicon.ico', '/admin/api/'
    )

    @app.before_request
    def track_visit():
        # 정적 파일, 봇 경로 제외
        if request.path.startswith(EXCLUDE_PREFIXES):
            return

        # API 호출 제외 (AJAX)
        if request.is_xhr if hasattr(request, 'is_xhr') else request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return

        try:
            visit = PageVisit(
                ip_address=request.remote_addr or '0.0.0.0',
                path=request.path[:500],
                user_id=current_user.id if current_user.is_authenticated else None,
                user_agent=(request.user_agent.string or '')[:500],
                referrer=(request.referrer or '')[:500]
            )
            db.session.add(visit)
            db.session.commit()
        except Exception:
            db.session.rollback()
