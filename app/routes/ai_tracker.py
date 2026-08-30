"""AI 행정 트래커 공개 대시보드 (/ai-tracker) — '일보 + 전수 대장' 구조

- /ai-tracker            : 광역16+기초228=244개 전수 대장 (0건 포함, 정렬·탭)
- /ai-tracker/gov/<명>   : 단체별 상세 — 올해 AI 사업 전건 (생략 금지)
- /ai-tracker/export.csv : 대장 CSV (길이 제한 없음)
- /ai-tracker/export.md  : 244 요약 마크다운
- /ai-tracker/methodology: 분류 기준 전문

비공개 게이트: AI_TRACKER_SECRET(?key= 최초 1회, 이후 쿠키).
AI_TRACKER_PUBLIC=true 로 오픈. 집계 기준: ai_verdict='예' AND is_latest
AND 취소공고 제외 (방법론 문서와 동일).
"""
import io
import os
import csv
from datetime import date
from flask import Blueprint, render_template, request, abort, make_response, Response
from sqlalchemy import text
from app import db

bp = Blueprint('ai_tracker', __name__, url_prefix='/ai-tracker')

COOKIE = "ai_tracker_key"
VALID = "ai_verdict='예' AND is_latest AND status NOT LIKE '%취소%'"


def _gate():
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
    try:
        return db.session.execute(text(sql), params).fetchall()
    except Exception:
        db.session.rollback()
        return []


def _all_govs():
    """광역 16 + 기초 228 = 244개 전체 명단 (매핑 파일 기준)."""
    from g2b_tracker import _load_mapping
    m = _load_mapping()
    metros = list(m["광역"].keys())
    basics = [f"{metro} {b}" for metro, bl in m["기초"].items() for b in bl]
    return metros, basics


def _stats_by_gov(org_tag: str | None = None):
    """gov_name → (건수, 총액, 최근 공고일). org_tag 지정 시 해당 태그만."""
    cond = "AND org_tag = :tag" if org_tag else ""
    rows = _q(f"""
        SELECT gov_name, COUNT(*), COALESCE(SUM(est_price),0), MAX(notice_date)
        FROM ai_projects WHERE {VALID} AND gov_name <> '미분류' {cond}
        GROUP BY gov_name""", **({"tag": org_tag} if org_tag else {}))
    return {r[0]: (r[1], int(r[2] or 0), r[3]) for r in rows}


def _ledger(tab: str, sort: str):
    """244 전수 대장 행 구성 — 0건 단체 포함."""
    metros, basics = _all_govs()
    tag = {"edu": "교육청", "corp": "공사공단"}.get(tab)
    stats = _stats_by_gov(tag)

    def row(name, level):
        c, a, d = stats.get(name, (0, 0, None))
        return {"name": name, "level": level, "cnt": c, "amt": a, "last": d}

    rows = [row(m, "광역") for m in metros] + [row(b, "기초") for b in basics]
    if sort == "amt":
        rows.sort(key=lambda r: (-r["amt"], -r["cnt"], r["name"]))
    else:
        rows.sort(key=lambda r: (-r["cnt"], -r["amt"], r["name"]))
    return rows


@bp.route('/')
def index():
    supplied = _gate()
    tab = request.args.get("tab", "all")          # all / edu / corp
    sort = request.args.get("sort", "cnt")        # cnt / amt
    rows = _ledger(tab, sort)

    total = _q(f"""SELECT COUNT(*), COALESCE(SUM(est_price),0),
                          MIN(notice_date), MAX(notice_date)
                   FROM ai_projects WHERE {VALID} AND gov_name <> '미분류'""")
    n, amt, d_from, d_to = (total[0] if total else (0, 0, None, None))
    verdicts = dict((r[0], r[1]) for r in _q(
        "SELECT ai_verdict, COUNT(*) FROM ai_projects WHERE is_latest GROUP BY ai_verdict"))
    nonzero = sum(1 for r in rows if r["cnt"] > 0)

    resp = make_response(render_template(
        'ai_tracker/index.html', rows=rows, tab=tab, sort=sort,
        total_count=n, total_amount=int(amt or 0), date_from=d_from, date_to=d_to,
        verdicts=verdicts, nonzero=nonzero))
    if supplied:
        resp.set_cookie(COOKIE, supplied, max_age=30 * 24 * 3600, httponly=True)
    return resp


@bp.route('/gov/<path:gov>')
def gov_detail(gov):
    _gate()
    projects = _q("""
        SELECT bid_name, est_price, contract_amount, notice_date, src_type,
               org_name, org_tag, status, notice_url, bid_no
        FROM ai_projects
        WHERE gov_name = :g AND ai_verdict='예' AND is_latest
        ORDER BY notice_date DESC NULLS LAST""", g=gov)
    summary = _q(f"""SELECT COUNT(*), COALESCE(SUM(est_price),0)
                     FROM ai_projects WHERE gov_name = :g AND {VALID}""", g=gov)
    cnt, amt = (summary[0] if summary else (0, 0))
    pending = _q("""SELECT COUNT(*) FROM ai_projects
                    WHERE gov_name = :g AND ai_verdict='애매' AND is_latest""", g=gov)
    return render_template('ai_tracker/gov.html', gov=gov, projects=projects,
                           cnt=cnt, amt=int(amt or 0),
                           pending=(pending[0][0] if pending else 0))


@bp.route('/export.csv')
def export_csv():
    _gate()
    rows = _q("""
        SELECT bid_no, bid_name, org_name, gov_level, gov_name, org_tag,
               est_price, contract_amount, notice_date, status, src_type,
               ai_verdict, notice_url
        FROM ai_projects WHERE ai_verdict='예' AND is_latest
        ORDER BY notice_date DESC NULLS LAST""")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["공고번호", "공고명", "수요기관", "광역기초", "지자체", "기관태그",
                "추정가격", "계약금액", "공고일", "상태", "업무구분", "판정", "원문링크"])
    for r in rows:
        w.writerow(list(r))
    out = "﻿" + buf.getvalue()   # BOM: 엑셀 한글 호환
    return Response(out, mimetype="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=ai_tracker_{date.today()}.csv"})


@bp.route('/export.md')
def export_md():
    _gate()
    rows = _ledger("all", "cnt")
    lines = [f"# 전국 244개 지자체 AI 발주 대장 ({date.today()})", "",
             "| 단체 | 구분 | 사업수 | 발주총액(억) | 최근 공고일 |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['level']} | {r['cnt']} | "
                     f"{r['amt']/1e8:.1f} | {r['last'] or '—'} |")
    lines += ["", "> 나라장터 발주 공고 기준 집계 — 예산 편성액과 다름."]
    return Response("\n".join(lines), mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             f"attachment; filename=ai_tracker_{date.today()}.md"})


@bp.route('/methodology')
def methodology():
    _gate()
    from g2b_tracker import AI_KEYWORDS
    return render_template('ai_tracker/methodology.html', keywords=AI_KEYWORDS)
