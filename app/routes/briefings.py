"""브리핑 아카이브 라우트"""
from flask import Blueprint, render_template, request
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
