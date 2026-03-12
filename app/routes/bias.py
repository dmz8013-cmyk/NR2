"""뉴스 편향 투표 시스템 라우트"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.bias import NewsArticle, BiasVote, BoneTransaction, get_media_bias
from datetime import datetime

bp = Blueprint('bias', __name__, url_prefix='/bias')


@bp.route('/')
def index():
    """편향 투표 메인 페이지"""
    page = request.args.get('page', 1, type=int)
    articles = NewsArticle.query.order_by(
        NewsArticle.created_at.desc()
    ).paginate(page=page, per_page=20, error_out=False)
    return render_template('bias/index.html', articles=articles)


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
        current_user.add_bones(2, 'article_submit')
        db.session.commit()

        flash('기사가 등록되었습니다! +2 🦴', 'success')
        return redirect(url_for('bias.detail', article_id=article.id))

    return render_template('bias/submit.html')


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
