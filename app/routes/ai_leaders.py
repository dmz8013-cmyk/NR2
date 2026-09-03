"""AI 거두 워치 공개 페이지 — /ai-leaders/ (로그인 없이 공개)

- /ai-leaders/            : 최신 발행분 + 지난 발행 날짜 인덱스
- /ai-leaders/<YYYY-MM-DD>: 해당일 영구 페이지 (OG 태그, 모바일 1열, 링크 복사)
데이터: leader_posts (published=TRUE), 텔레그램 발행과 동시 적재됨.
"""
import os
from flask import Blueprint, render_template, abort
from sqlalchemy import text
from app import db

bp = Blueprint('ai_leaders', __name__, url_prefix='/ai-leaders')


def _q(sql, **params):
    try:
        return db.session.execute(text(sql), params).fetchall()
    except Exception:
        db.session.rollback()
        return []


def _cta():
    return (os.environ.get("KAKAO_LINK", "https://buly.kr/7mBN720"),
            os.environ.get("TELE_LINK", "https://t.me/gazzzza2025"))


def _posts_of(date):
    return _q("""SELECT name, handle, tier, post_url, summary_ko, score, bias_label
                 FROM leader_posts WHERE date = :d AND published
                 ORDER BY score DESC, id""", d=date)


@bp.route('/')
def index():
    dates = _q("""SELECT date, COUNT(*) FROM leader_posts WHERE published
                  GROUP BY date ORDER BY date DESC LIMIT 60""")
    latest = dates[0][0] if dates else None
    posts = _posts_of(latest) if latest else []
    kakao, tele = _cta()
    md = f"{latest.month}/{latest.day}" if latest else ""
    return render_template('ai_leaders/day.html', date=latest, md=md, posts=posts,
                           dates=dates, is_index=True, kakao=kakao, tele=tele)


@bp.route('/<date>')
def day(date):
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        abort(404)
    posts = _posts_of(date)
    if not posts:
        abort(404)
    kakao, tele = _cta()
    md = f"{int(date[5:7])}/{int(date[8:10])}"
    return render_template('ai_leaders/day.html', date=date, md=md, posts=posts,
                           dates=[], is_index=False, kakao=kakao, tele=tele)
