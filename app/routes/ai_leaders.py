"""누렁이 시그널 공개 페이지 — /signal/ (로그인 없이 공개)

- /signal/            : 최신 발행분 + 지난 발행 날짜 인덱스
- /signal/<YYYY-MM-DD>: 해당일 영구 페이지 (OG 태그, 모바일 1열, 링크 복사)
- /ai-leaders/*       : 구 경로 — /signal/* 로 301 영구 리다이렉트
데이터: leader_posts (published=TRUE), 텔레그램 발행과 동시 적재됨.
related=TRUE 행은 클러스터 초과분 — 본문 카드가 아닌 '관련 링크'로만 노출.
"""
import os
import re
from flask import Blueprint, render_template, abort, redirect

from sqlalchemy import text
from app import db

bp = Blueprint('ai_leaders', __name__, url_prefix='/signal')
legacy_bp = Blueprint('ai_leaders_legacy', __name__, url_prefix='/ai-leaders')

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


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
    rows = _q("""SELECT name, handle, tier, post_url, summary_ko, score, bias_label,
                        COALESCE(related, FALSE)
                 FROM leader_posts WHERE date = :d AND published
                 ORDER BY score DESC NULLS LAST, id""", d=date)
    if not rows:  # related 컬럼 미생성 구버전 DB 폴백
        rows = [r + (False,) for r in
                _q("""SELECT name, handle, tier, post_url, summary_ko, score, bias_label
                      FROM leader_posts WHERE date = :d AND published
                      ORDER BY score DESC NULLS LAST, id""", d=date)]
    return ([r for r in rows if not r[7]], [r for r in rows if r[7]])


def _render(date, posts, related, dates, is_index):
    kakao, tele = _cta()
    md = f"{int(str(date)[5:7])}/{int(str(date)[8:10])}" if date else ""
    return render_template('ai_leaders/day.html', date=date, md=md, posts=posts,
                           related=related, dates=dates, is_index=is_index,
                           kakao=kakao, tele=tele)


@bp.route('/')
def index():
    dates = _q("""SELECT date, COUNT(*) FROM leader_posts
                  WHERE published AND NOT COALESCE(related, FALSE)
                  GROUP BY date ORDER BY date DESC LIMIT 60""")
    latest = dates[0][0] if dates else None
    posts, related = _posts_of(latest) if latest else ([], [])
    return _render(latest, posts, related, dates, True)


@bp.route('/<date>')
def day(date):
    if not DATE_RE.fullmatch(date):
        abort(404)
    posts, related = _posts_of(date)
    if not posts and not related:
        abort(404)
    return _render(date, posts, related, [], False)


@legacy_bp.route('/')
def legacy_index():
    return redirect('/signal/', code=301)


@legacy_bp.route('/<date>')
def legacy_day(date):
    if not DATE_RE.fullmatch(date):
        abort(404)
    return redirect(f'/signal/{date}', code=301)
