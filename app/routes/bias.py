"""뉴스 편향 투표 시스템 라우트"""
import os
import json
import traceback
import difflib
import requests as http_requests
from bs4 import BeautifulSoup
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db, csrf
from app.models.bias import NewsArticle, BiasVote, BoneTransaction, ArticleCluster, get_media_bias
from datetime import datetime, timedelta

bp = Blueprint('bias', __name__, url_prefix='/bias')


@bp.route('/debug')
def debug():
    """디버그 엔드포인트 - 에러 원인 확인용"""
    try:
        from sqlalchemy import text
        with db.engine.connect() as conn:
            cols = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'news_articles' ORDER BY ordinal_position"
            )).fetchall()
            col_names = [c[0] for c in cols]

        page = request.args.get('page', 1, type=int)
        articles = NewsArticle.query.order_by(
            NewsArticle.created_at.desc()
        ).paginate(page=page, per_page=20, error_out=False)
        # 프로퍼티 접근 테스트
        prop_test = []
        for a in articles.items:
            prop_test.append({
                'id': a.id,
                'vote_total': a.vote_total,
                'vote_total_type': type(a.vote_total).__name__,
                'bias_label': a.bias_label,
                'left_pct': a.left_pct,
            })

        # 템플릿 렌더링 테스트
        html = render_template('bias/index.html', articles=articles)

        return jsonify({
            'status': 'ok',
            'db_columns': col_names,
            'article_count': articles.total,
            'prop_test': prop_test,
            'template_ok': True,
            'html_length': len(html),
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'traceback': traceback.format_exc(),
        }), 500


@bp.route('/')
def index():
    """편향 투표 메인 페이지"""
    try:
        page = request.args.get('page', 1, type=int)
        tab = request.args.get('tab', 'all')

        query = NewsArticle.query
        if tab == 'ranking':
            query = query.filter(NewsArticle.is_ranking == True)
        elif tab == 'cluster':
            query = query.filter(NewsArticle.cluster_id.isnot(None))
        elif tab == 'politics':
            query = query.filter(
                db.or_(
                    NewsArticle.ranking_section == '정치',
                    NewsArticle.title.ilike('%정치%'),
                    NewsArticle.title.ilike('%대통령%'),
                    NewsArticle.title.ilike('%국회%'),
                    NewsArticle.title.ilike('%선거%'),
                    NewsArticle.title.ilike('%여당%'),
                    NewsArticle.title.ilike('%야당%'),
                )
            )
        elif tab == 'economy':
            query = query.filter(
                db.or_(
                    NewsArticle.ranking_section == '경제',
                    NewsArticle.title.ilike('%경제%'),
                    NewsArticle.title.ilike('%증시%'),
                    NewsArticle.title.ilike('%환율%'),
                    NewsArticle.title.ilike('%부동산%'),
                    NewsArticle.title.ilike('%금리%'),
                    NewsArticle.title.ilike('%주가%'),
                )
            )
        elif tab == 'world':
            query = query.filter(
                db.or_(
                    NewsArticle.ranking_section == '세계',
                    NewsArticle.title.ilike('%미국%'),
                    NewsArticle.title.ilike('%중국%'),
                    NewsArticle.title.ilike('%일본%'),
                    NewsArticle.title.ilike('%러시아%'),
                    NewsArticle.title.ilike('%우크라%'),
                    NewsArticle.title.ilike('%북한%'),
                    NewsArticle.title.ilike('%트럼프%'),
                )
            )

        articles = query.order_by(
            NewsArticle.created_at.desc()
        ).paginate(page=page, per_page=20, error_out=False)
        return render_template('bias/index.html', articles=articles, current_tab=tab)
    except Exception as e:
        current_app.logger.error(f'[BIAS INDEX ERROR] {traceback.format_exc()}')
        raise


@bp.route('/submit', methods=['GET', 'POST'])
@login_required
def submit():
    """기사 등록"""
    if current_user.verify_tier == 'bronze':
        flash('편향 투표 참여를 위해 본인인증이 필요합니다.', 'warning')
        return redirect(url_for('bias.index'))

    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        title = request.form.get('title', '').strip()
        source = request.form.get('source', '').strip()
        summary = request.form.get('summary', '').strip()

        if not url or not title:
            flash('URL과 제목은 필수입니다.', 'error')
            return redirect(url_for('bias.submit'))

        existing = NewsArticle.query.filter_by(url=url).first()
        if existing:
            flash('이미 등록된 기사입니다.', 'warning')
            return redirect(url_for('bias.detail', article_id=existing.id))

        bias = get_media_bias(source)
        article = NewsArticle(
            url=url, title=title, source=source,
            summary=summary, submitted_by=current_user.id,
            source_political=bias['political'],
            source_geopolitical=bias['geopolitical'],
            source_economic=bias['economic']
        )
        db.session.add(article)
        db.session.flush()  # article.id 확보
        _auto_cluster(article)
        current_user.add_bones(2, 'article_submit')
        db.session.commit()

        flash('기사가 등록되었습니다! +2 🦴', 'success')
        return redirect(url_for('bias.detail', article_id=article.id))

    return render_template('bias/submit.html')


def _auto_cluster(article):
    """새 기사를 기존 클러스터에 매칭하거나 새 클러스터 생성"""
    # 최근 3일 내 기사와 비교
    cutoff = datetime.utcnow() - timedelta(days=3)
    recent = NewsArticle.query.filter(
        NewsArticle.id != article.id,
        NewsArticle.created_at >= cutoff,
    ).all()

    best_match = None
    best_ratio = 0.0

    for other in recent:
        ratio = difflib.SequenceMatcher(None, article.title, other.title).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = other

    if best_ratio >= 0.70 and best_match:
        if best_match.cluster_id:
            # 기존 클러스터에 합류
            article.cluster_id = best_match.cluster_id
        else:
            # 새 클러스터 생성, 두 기사 모두 묶기
            cluster = ArticleCluster(title=best_match.title)
            db.session.add(cluster)
            db.session.flush()
            best_match.cluster_id = cluster.id
            article.cluster_id = cluster.id


@bp.route('/cluster/<int:cluster_id>')
def cluster_detail(cluster_id):
    """같은 사건 다른 언론사 비교"""
    cluster = ArticleCluster.query.get_or_404(cluster_id)
    articles = cluster.articles.order_by(NewsArticle.created_at.desc()).all()
    return render_template('bias/cluster.html', cluster=cluster, articles=articles)


@bp.route('/<int:article_id>')
def detail(article_id):
    """기사 상세 + 투표"""
    article = NewsArticle.query.get_or_404(article_id)
    user_vote = None
    if current_user.is_authenticated:
        user_vote = BiasVote.query.filter_by(
            user_id=current_user.id, article_id=article_id
        ).first()
    return render_template('bias/detail.html', article=article, user_vote=user_vote)


@bp.route('/<int:article_id>/vote', methods=['POST'])
@login_required
def vote(article_id):
    """편향 투표 처리"""
    if current_user.verify_tier == 'bronze':
        flash('본인인증 후 투표할 수 있습니다.', 'warning')
        return redirect(url_for('bias.detail', article_id=article_id))

    article = NewsArticle.query.get_or_404(article_id)
    bias = request.form.get('bias')

    if bias not in ('left', 'center', 'right'):
        flash('올바른 투표 옵션을 선택하세요.', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    existing = BiasVote.query.filter_by(
        user_id=current_user.id, article_id=article_id
    ).first()

    if existing:
        existing.bias = bias
        flash('투표가 변경되었습니다.', 'success')
    else:
        new_vote = BiasVote(
            user_id=current_user.id,
            article_id=article_id,
            bias=bias
        )
        db.session.add(new_vote)
        current_user.add_bones(1, 'bias_vote')
        current_user.total_bias_votes += 1
        flash('투표 완료! +1 🦴', 'success')

    article.recalculate()
    db.session.commit()

    return redirect(url_for('bias.detail', article_id=article_id))


@bp.route('/<int:article_id>/delete', methods=['POST'])
@login_required
def delete_article(article_id):
    """관리자 전용 기사 삭제"""
    if not current_user.is_admin:
        flash('관리자만 삭제할 수 있습니다.', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    article = NewsArticle.query.get_or_404(article_id)
    db.session.delete(article)
    db.session.commit()
    flash('기사가 삭제되었습니다.', 'success')
    return redirect(url_for('bias.index'))


# --- AI 편향 분석 ---

def _scrape_article(url):
    """기사 URL에서 본문 텍스트 추출 (urllib 사용)"""
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or 'utf-8'
        html = raw.decode(charset, errors='replace')
    soup = BeautifulSoup(html, 'lxml')

    # 네이버 뉴스
    body = soup.select_one('#dic_area, #newsct_article, .newsct_body, article#dic_area')
    if not body:
        # 일반 기사 사이트
        body = soup.select_one('article, .article-body, .article_body, .story-body, #article-body, .news_end')
    if not body:
        # 최후 수단: 가장 긴 <p> 그룹
        paragraphs = soup.find_all('p')
        text = '\n'.join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
        return text[:5000] if text else ''

    # 불필요 요소 제거
    for tag in body.select('script, style, .ad, .adsbygoogle, .journalist_area, .byline'):
        tag.decompose()

    text = body.get_text('\n', strip=True)
    return text[:5000].encode('utf-8', errors='ignore').decode('utf-8')


def _sanitize_text(text):
    """JSON 직렬화가 불가능한 문자(서로게이트 등) 제거"""
    if not text:
        return ''
    return text.encode('utf-8', errors='ignore').decode('utf-8')


def _analyze_with_ai(title, body_text, source=''):
    """Claude Haiku로 3축 편향 분석 (urllib 사용 — 인코딩 안전)"""
    import urllib.request

    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise ValueError('ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다')

    # 깨진 유니코드 문자 제거
    title = _sanitize_text(title)
    body_text = _sanitize_text(body_text)
    source = _sanitize_text(source)

    prompt = (
        "다음 한국 뉴스 기사의 편향을 3개 축으로 분석해주세요.\n\n"
        f"기사 제목: {title}\n"
        f"언론사: {source}\n"
        f"기사 본문:\n{body_text}\n\n"
        "각 축에 대해 -100 ~ +100 점수와 근거를 제시하세요:\n"
        "1. 정치축 (political): 진보(-100) ↔ 보수(+100)\n"
        "2. 지정학축 (geopolitical): 친중(-100) ↔ 친미(+100)\n"
        "3. 경제축 (economic): 노동친화(-100) ↔ 대기업친화(+100)\n\n"
        '반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:\n'
        '{"political": 점수, "geopolitical": 점수, "economic": 점수, "summary": "2~3문장 요약"}'
    )

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }
    # json.dumps 기본값 ensure_ascii=True → 한글이 \uXXXX 이스케이프 → 순수 ASCII
    data = json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "X-Api-Key": api_key,
            "Anthropic-Version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        message = json.loads(resp.read().decode('utf-8'))

    raw = message['content'][0]['text'].strip()
    # JSON 블록 추출
    if '```' in raw:
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # 범위 클램핑
    for key in ('political', 'geopolitical', 'economic'):
        val = result.get(key, 0)
        result[key] = max(-100, min(100, int(val)))

    return result


@bp.route('/<int:article_id>/analyze', methods=['POST'])
@login_required
def analyze(article_id):
    """AI 편향 분석 실행"""
    if not current_user.is_admin:
        flash('관리자만 AI 분석을 실행할 수 있습니다.', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    article = NewsArticle.query.get_or_404(article_id)

    # 1단계: 기사 스크래핑
    try:
        body_text = _scrape_article(article.url)
    except Exception as e:
        current_app.logger.error(f'[SCRAPE ERROR] {traceback.format_exc()}')
        flash(f'기사 수집 실패: {type(e).__name__}', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    if not body_text or len(body_text) < 50:
        flash('기사 본문을 추출할 수 없습니다.', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    # 2단계: AI 분석
    try:
        result = _analyze_with_ai(article.title, body_text, article.source or '')
    except json.JSONDecodeError:
        flash('AI 응답 파싱 실패. 다시 시도해주세요.', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))
    except Exception as e:
        current_app.logger.error(f'[AI API ERROR] {traceback.format_exc()}')
        flash(f'AI 분석 실패: {type(e).__name__}', 'error')
        return redirect(url_for('bias.detail', article_id=article_id))

    # 3단계: DB 저장
    try:
        article.article_political = result['political']
        article.article_geopolitical = result['geopolitical']
        article.article_economic = result['economic']
        article.ai_summary = result.get('summary', '')
        db.session.commit()
        flash('AI 편향 분석이 완료되었습니다.', 'success')
    except Exception as e:
        current_app.logger.error(f'[DB SAVE ERROR] {traceback.format_exc()}')
        flash(f'결과 저장 실패: {type(e).__name__}', 'error')

    return redirect(url_for('bias.detail', article_id=article_id))


# --- 주간 편향 리포트 ---

@bp.route('/report/weekly')
@login_required
def weekly_report():
    """주간 편향 리포트 미리보기 (관리자 전용)"""
    if not current_user.is_admin:
        flash('관리자만 접근할 수 있습니다.', 'error')
        return redirect(url_for('bias.index'))

    from app.utils.bias_report import generate_weekly_report
    report = generate_weekly_report()
    return render_template('bias/report.html', report=report)


@bp.route('/report/send', methods=['POST'])
@login_required
def send_report():
    """주간 리포트 텔레그램 전송 (관리자 전용)"""
    if not current_user.is_admin:
        flash('관리자만 접근할 수 있습니다.', 'error')
        return redirect(url_for('bias.index'))

    from app.utils.bias_report import generate_weekly_report, send_weekly_report_to_telegram
    report = generate_weekly_report()
    result = send_weekly_report_to_telegram(report['telegram_text'])

    if result['success']:
        flash('주간 리포트가 텔레그램으로 전송되었습니다.', 'success')
    else:
        flash(f'전송 실패: {result["message"]}', 'error')

    return redirect(url_for('bias.weekly_report'))


# --- 클릭 트래킹 & 나의 편향 리포트 ---

@bp.route('/track-click', methods=['POST'])
@csrf.exempt
def track_click():
    """기사 클릭 시 편향값 누적 저장 (비로그인 포함)"""
    from app.models.user_bias_log import UserBiasLog
    import uuid

    data = request.get_json(silent=True) or {}
    article_id = data.get('article_id')
    if not article_id:
        return jsonify({'ok': False}), 400

    article = NewsArticle.query.get(article_id)
    if not article:
        return jsonify({'ok': False}), 404

    # 세션 ID 관리
    session_id = request.cookies.get('nr2_sid')
    if not session_id:
        session_id = uuid.uuid4().hex

    user_id = current_user.id if current_user.is_authenticated else None

    log = UserBiasLog(
        session_id=session_id,
        user_id=user_id,
        article_id=article.id,
        source_political=article.source_political,
        source_geopolitical=article.source_geopolitical,
        source_economic=article.source_economic,
    )
    db.session.add(log)
    db.session.commit()

    resp = jsonify({'ok': True})
    if not request.cookies.get('nr2_sid'):
        resp.set_cookie('nr2_sid', session_id, max_age=365 * 24 * 3600, httponly=True, samesite='Lax')
    return resp


@bp.route('/my-report')
def my_report():
    """나의 편향 리포트 페이지"""
    from app.models.user_bias_log import UserBiasLog
    from sqlalchemy import func

    # 로그인 사용자 → user_id, 비로그인 → session cookie
    if current_user.is_authenticated:
        logs_query = UserBiasLog.query.filter_by(user_id=current_user.id)
    else:
        session_id = request.cookies.get('nr2_sid')
        if not session_id:
            return render_template('bias/my_report.html', has_data=False, count=0)
        logs_query = UserBiasLog.query.filter_by(session_id=session_id)

    count = logs_query.count()
    if count == 0:
        return render_template('bias/my_report.html', has_data=False, count=0)

    # 편향값이 있는 로그만 평균 계산
    avg = db.session.query(
        func.avg(UserBiasLog.source_political),
        func.avg(UserBiasLog.source_geopolitical),
        func.avg(UserBiasLog.source_economic),
    ).filter(
        UserBiasLog.id.in_([l.id for l in logs_query])
    ).first()

    pol = round(avg[0] or 0, 1)
    geo = round(avg[1] or 0, 1)
    eco = round(avg[2] or 0, 1)

    # 한 줄 성향 요약 생성
    def label(score):
        if score <= -30:
            return '진보'
        elif score <= -10:
            return '중도 진보'
        elif score <= 10:
            return '중도'
        elif score <= 30:
            return '중도 보수'
        else:
            return '보수'

    summary = f"당신은 {label(pol)} 성향의 뉴스를 주로 봅니다"

    return render_template('bias/my_report.html',
                           has_data=True,
                           count=count,
                           pol=pol, geo=geo, eco=eco,
                           pol_label=label(pol),
                           geo_label=label(geo),
                           eco_label=label(eco),
                           summary=summary)
