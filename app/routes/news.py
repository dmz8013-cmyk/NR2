from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import BreakingNews

bp = Blueprint('news', __name__, url_prefix='/news')


@bp.route('/breaking')
def breaking():
    """속보 목록"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # 활성화된 속보만 조회, 우선순위 높은 순
    query = BreakingNews.query.filter_by(is_active=True).order_by(
        BreakingNews.priority.desc(),
        BreakingNews.created_at.desc()
    )

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    news_list = pagination.items

    return render_template('news/breaking.html',
                          news_list=news_list,
                          pagination=pagination)


@bp.route('/breaking/<int:news_id>')
def view(news_id):
    """속보 상세"""
    news = BreakingNews.query.get_or_404(news_id)
    return render_template('news/view.html', news=news)


@bp.route('/breaking/create', methods=['GET', 'POST'])
@login_required
def create():
    """속보 작성 (관리자만)"""
    if not current_user.is_admin:
        flash('관리자만 속보를 작성할 수 있습니다.', 'error')
        return redirect(url_for('news.breaking'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip()
        priority = request.form.get('priority', 0, type=int)

        # 유효성 검사
        if not title:
            flash('제목을 입력해주세요.', 'error')
            return render_template('news/create.html')

        if not content:
            flash('내용을 입력해주세요.', 'error')
            return render_template('news/create.html')

        # 속보 생성
        news = BreakingNews(
            title=title,
            content=content,
            source=source,
            priority=priority,
            user_id=current_user.id
        )
        db.session.add(news)
        db.session.commit()

        flash('속보가 등록되었습니다.', 'success')
        return redirect(url_for('news.view', news_id=news.id))

    return render_template('news/create.html')


@bp.route('/breaking/<int:news_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(news_id):
    """속보 수정 (관리자만)"""
    news = BreakingNews.query.get_or_404(news_id)

    if not current_user.is_admin:
        flash('관리자만 속보를 수정할 수 있습니다.', 'error')
        return redirect(url_for('news.view', news_id=news_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        source = request.form.get('source', '').strip()
        priority = request.form.get('priority', 0, type=int)

        if not title or not content:
            flash('제목과 내용을 입력해주세요.', 'error')
            return render_template('news/edit.html', news=news)

        news.title = title
        news.content = content
        news.source = source
        news.priority = priority
        news.updated_at = datetime.utcnow()

        db.session.commit()

        flash('속보가 수정되었습니다.', 'success')
        return redirect(url_for('news.view', news_id=news_id))

    return render_template('news/edit.html', news=news)


@bp.route('/breaking/<int:news_id>/delete', methods=['POST'])
@login_required
def delete(news_id):
    """속보 삭제 (관리자만)"""
    news = BreakingNews.query.get_or_404(news_id)

    if not current_user.is_admin:
        flash('관리자만 속보를 삭제할 수 있습니다.', 'error')
        return redirect(url_for('news.view', news_id=news_id))

    db.session.delete(news)
    db.session.commit()

    flash('속보가 삭제되었습니다.', 'success')
    return redirect(url_for('news.breaking'))


@bp.route('/breaking/<int:news_id>/toggle', methods=['POST'])
@login_required
def toggle_active(news_id):
    """속보 활성화/비활성화 (관리자만)"""
    news = BreakingNews.query.get_or_404(news_id)

    if not current_user.is_admin:
        flash('관리자만 속보 상태를 변경할 수 있습니다.', 'error')
        return redirect(url_for('news.view', news_id=news_id))

    news.is_active = not news.is_active
    db.session.commit()

    status = '활성화' if news.is_active else '비활성화'
    flash(f'속보가 {status}되었습니다.', 'success')
    return redirect(url_for('news.view', news_id=news_id))
