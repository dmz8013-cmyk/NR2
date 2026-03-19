"""브리핑 아카이브 라우트"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models.briefing import Briefing
from app import db

bp = Blueprint('briefings', __name__, url_prefix='/briefings')


@bp.route('/')
def index():
    """브리핑 아카이브 메인"""
    page = request.args.get('page', 1, type=int)
    btype = request.args.get('type', '')

    query = Briefing.query

    if btype:
        query = query.filter_by(briefing_type=btype)

    briefings = query.order_by(Briefing.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )

    return render_template('briefings/index.html',
                           briefings=briefings,
                           current_type=btype)


@bp.route('/<int:briefing_id>')
def detail(briefing_id):
    """브리핑 상세 보기"""
    briefing = Briefing.query.get_or_404(briefing_id)

    prev_briefing = Briefing.query.filter(
        Briefing.id < briefing_id
    ).order_by(Briefing.id.desc()).first()

    next_briefing = Briefing.query.filter(
        Briefing.id > briefing_id
    ).order_by(Briefing.id.asc()).first()

    return render_template('briefings/detail.html',
                           briefing=briefing,
                           prev_briefing=prev_briefing,
                           next_briefing=next_briefing)


@bp.route('/<int:briefing_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(briefing_id):
    """브리핑 수정 (관리자 전용)"""
    if not current_user.is_admin:
        flash('관리자만 수정할 수 있습니다.', 'danger')
        return redirect(url_for('briefings.detail', briefing_id=briefing_id))

    briefing = Briefing.query.get_or_404(briefing_id)

    if request.method == 'POST':
        briefing.title = request.form.get('title', briefing.title)
        briefing.content = request.form.get('content', briefing.content)
        db.session.commit()
        flash('브리핑이 수정되었습니다.', 'success')
        return redirect(url_for('briefings.detail', briefing_id=briefing_id))

    return render_template('briefings/edit.html', briefing=briefing)


@bp.route('/<int:briefing_id>/delete', methods=['POST'])
@login_required
def delete(briefing_id):
    """브리핑 삭제 (관리자 전용)"""
    if not current_user.is_admin:
        flash('관리자만 삭제할 수 있습니다.', 'danger')
        return redirect(url_for('briefings.detail', briefing_id=briefing_id))

    briefing = Briefing.query.get_or_404(briefing_id)
    db.session.delete(briefing)
    db.session.commit()
    flash('브리핑이 삭제되었습니다.', 'success')
    return redirect(url_for('briefings.index'))
