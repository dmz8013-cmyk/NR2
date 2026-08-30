"""AI 행정 트래커 공개 대시보드 (/ai-tracker) — Phase 1

공개 전 비공개 상태: 환경변수 AI_TRACKER_SECRET 가 설정된 경우
?key=<secret> 쿼리(최초 1회, 이후 쿠키)로만 접근 가능.
AI_TRACKER_SECRET 미설정 시 404 (기본 잠금).
검수 후 오픈: AI_TRACKER_PUBLIC=true 로 게이트 해제.
"""
import os
from flask import Blueprint, render_template, request, abort, make_response
from sqlalchemy import text
from app import db

bp = Blueprint('ai_tracker', __name__, url_prefix='/ai-tracker')

COOKIE = "ai_tracker_key"


def _gate():
    """비공개 게이트. 공개 플래그 ON이면 통과."""
    if os.environ.get("AI_TRACKER_PUBLIC", "false").lower() == "true":
        return None
    secret = os.environ.get("AI_TRACKER_SECRET")
    if not secret:
        abort(404)
    supplied = request.args.get("key") or request.cookies.get(COOKIE)
    if supplied != secret:
        abort(404)
    return supplied


def _q(sql, **params):
    """조회 실패 시 빈 결과 (테이블 미생성 등) — 페이지는 항상 뜬다."""
    try:
        return db.session.execute(text(sql), params).fetchall()
    except Exception:
        db.session.rollback()
        return []


@bp.route('/')
def index():
    supplied = _gate()

    # 방법론 문서와 일치: 상단 총계는 지자체 매핑 건 기준 (미분류는 데이터만 보존)
    total = _q("""SELECT COUNT(*), COALESCE(SUM(est_price),0),
                         MIN(notice_date), MAX(notice_date)
                  FROM ai_projects WHERE ai_verdict='예' AND gov_name <> '미분류'""")
    n, amt, d_from, d_to = (total[0] if total else (0, 0, None, None))

    verdicts = dict((r[0], r[1]) for r in _q(
        "SELECT ai_verdict, COUNT(*) FROM ai_projects GROUP BY ai_verdict"))

    metro = _q("""
        SELECT split_part(gov_name, ' ', 1) AS metro,
               COUNT(*) AS cnt, COALESCE(SUM(est_price),0) AS amt
        FROM ai_projects
        WHERE ai_verdict='예' AND gov_name <> '미분류'
        GROUP BY 1 ORDER BY cnt DESC""")

    basic = _q("""
        SELECT gov_name, COUNT(*) AS cnt, COALESCE(SUM(est_price),0) AS amt
        FROM ai_projects
        WHERE ai_verdict='예' AND gov_level='기초'
        GROUP BY 1 ORDER BY cnt DESC, amt DESC LIMIT 20""")

    recent = _q("""
        SELECT notice_date, gov_name, org_name, bid_name, est_price,
               contract_amount, src_type, org_tag
        FROM ai_projects WHERE ai_verdict='예'
        ORDER BY notice_date DESC NULLS LAST, collected_at DESC LIMIT 30""")

    resp = make_response(render_template(
        'ai_tracker/index.html',
        total_count=n, total_amount=amt, date_from=d_from, date_to=d_to,
        verdicts=verdicts, metro=metro, basic=basic, recent=recent))
    if supplied:
        resp.set_cookie(COOKIE, supplied, max_age=30 * 24 * 3600, httponly=True)
    return resp


@bp.route('/methodology')
def methodology():
    _gate()
    from g2b_tracker import AI_KEYWORDS
    return render_template('ai_tracker/methodology.html', keywords=AI_KEYWORDS)
