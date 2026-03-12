"""뉴스 편향 투표 시스템 라우트"""
import os
import json
import traceback
import difflib
import requests as http_requests
from bs4 import BeautifulSoup
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
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


@bp.route('/debug-key')
@login_required
def debug_key():
    """임시: ANTHROPIC_API_KEY 상태 확인 (관리자 전용)"""
    if not current_user.is_admin:
        return jsonify({'error': 'admin only'}), 403
    raw = os.environ.get('ANTHROPIC_API_KEY', '')
    stripped = raw.strip()
    return jsonify({
        'prefix': raw[:10],
        'raw_length': len(raw),
        'stripped_length': len(stripped),
        'repr_first_20': repr(raw[:20]),
        'has_whitespace': len(raw) != len(stripped),
    })


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
    """기사 URL에서 본문 텍스트 추출"""
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    resp = http_requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'lxml')

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
    return text[:5000]


def _analyze_with_ai(title, body_text, source=''):
    """Claude Haiku로 3축 편향 분석"""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        raise ValueError('ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다')

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""다음 한국 뉴스 기사의 편향을 3개 축으로 분석해주세요.

기사 제목: {title}
언론사: {source}
기사 본문:
{body_text}

각 축에 대해 -100 ~ +100 점수와 근거를 제시하세요:
1. 정치축 (political): 진보(-100) ↔ 보수(+100)
2. 지정학축 (geopolitical): 친중(-100) ↔ 친미(+100)
3. 경제축 (economic): 노동친화(-100) ↔ 대기업친화(+100)

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이 JSON만 출력하세요:
{{"political": 점수, "geopolitical": 점수, "economic": 점수, "summary": "2~3문장 요약"}}"""

    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=500,
        messages=[{'role': 'user', 'content': prompt}],
    )

    raw = message.content[0].text.strip()
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

    try:
        body_text = _scrape_article(article.url)
        if not body_text or len(body_text) < 50:
            flash('기사 본문을 추출할 수 없습니다.', 'error')
            return redirect(url_for('bias.detail', article_id=article_id))

        result = _analyze_with_ai(article.title, body_text, article.source or '')

        article.article_political = result['political']
        article.article_geopolitical = result['geopolitical']
        article.article_economic = result['economic']
        article.ai_summary = result.get('summary', '')
        db.session.commit()

        flash('AI 편향 분석이 완료되었습니다.', 'success')
    except json.JSONDecodeError:
        flash('AI 응답 파싱 실패. 다시 시도해주세요.', 'error')
    except Exception as e:
        current_app.logger.error(f'[AI ANALYZE ERROR] {traceback.format_exc()}')
        flash(f'분석 실패: {str(e)[:100]}', 'error')

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
