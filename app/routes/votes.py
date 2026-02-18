from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import Vote, VoteOption, VoteResponse

bp = Blueprint('votes', __name__, url_prefix='/votes')


@bp.route('/')
def list():
    """투표 목록"""
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('POSTS_PER_PAGE', 20)

    # 투표 목록 조회 (최신순)
    pagination = Vote.query.order_by(Vote.created_at.desc())\
                           .paginate(page=page, per_page=per_page, error_out=False)

    votes = pagination.items

    return render_template('votes/list.html',
                         votes=votes,
                         pagination=pagination)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """투표 생성"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_multiple = request.form.get('is_multiple') == 'on'
        end_date_str = request.form.get('end_date', '').strip()

        # 유효성 검사
        errors = []
        if not title:
            errors.append('투표 제목을 입력해주세요.')

        # 옵션 수집
        options = []
        for i in range(1, 11):  # 최대 10개
            option_text = request.form.get(f'option_{i}', '').strip()
            if option_text:
                options.append(option_text)

        if len(options) < 2:
            errors.append('최소 2개 이상의 선택지를 입력해주세요.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('votes/create.html')

        # 종료일 처리
        end_date = None
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            except ValueError:
                flash('올바른 날짜 형식이 아닙니다.', 'error')
                return render_template('votes/create.html')

        # 투표 생성
        vote = Vote(
            title=title,
            description=description,
            is_multiple=is_multiple,
            end_date=end_date,
            user_id=current_user.id
        )
        db.session.add(vote)
        db.session.flush()

        # 옵션 생성
        for idx, option_text in enumerate(options):
            option = VoteOption(
                text=option_text,
                order=idx,
                vote_id=vote.id
            )
            db.session.add(option)

        db.session.commit()

        flash('투표가 생성되었습니다.', 'success')
        return redirect(url_for('votes.view', vote_id=vote.id))

    return render_template('votes/create.html')


@bp.route('/<int:vote_id>')
def view(vote_id):
    """투표 상세 및 참여"""
    vote = Vote.query.get_or_404(vote_id)

    # 사용자가 이미 투표했는지 확인
    user_voted = False
    user_votes = []
    if current_user.is_authenticated:
        user_votes = VoteResponse.query.filter_by(
            user_id=current_user.id,
            vote_id=vote_id
        ).all()
        user_voted = len(user_votes) > 0

    return render_template('votes/view.html',
                         vote=vote,
                         user_voted=user_voted,
                         user_votes=user_votes)


@bp.route('/<int:vote_id>/vote', methods=['POST'])
@login_required
def submit_vote(vote_id):
    """투표 참여"""
    vote = Vote.query.get_or_404(vote_id)

    # 투표 종료 확인
    if not vote.is_active:
        flash('종료된 투표입니다.', 'error')
        return redirect(url_for('votes.view', vote_id=vote_id))

    # 이미 투표했는지 확인
    existing_votes = VoteResponse.query.filter_by(
        user_id=current_user.id,
        vote_id=vote_id
    ).all()

    if existing_votes and not vote.is_multiple:
        flash('이미 투표에 참여하셨습니다.', 'error')
        return redirect(url_for('votes.view', vote_id=vote_id))

    # 선택된 옵션 가져오기
    if vote.is_multiple:
        option_ids = request.form.getlist('options')
    else:
        option_id = request.form.get('option')
        option_ids = [option_id] if option_id else []

    if not option_ids:
        flash('선택지를 선택해주세요.', 'error')
        return redirect(url_for('votes.view', vote_id=vote_id))

    # 기존 투표 삭제 (복수 선택인 경우)
    if vote.is_multiple:
        for existing in existing_votes:
            db.session.delete(existing)

    # 투표 저장
    for option_id in option_ids:
        option = VoteOption.query.get(int(option_id))
        if option and option.vote_id == vote_id:
            response = VoteResponse(
                user_id=current_user.id,
                vote_id=vote_id,
                option_id=int(option_id)
            )
            db.session.add(response)

    db.session.commit()
    flash('투표가 완료되었습니다.', 'success')
    return redirect(url_for('votes.view', vote_id=vote_id))


@bp.route('/<int:vote_id>/delete', methods=['POST'])
@login_required
def delete(vote_id):
    """투표 삭제"""
    vote = Vote.query.get_or_404(vote_id)

    # 권한 확인
    if vote.user_id != current_user.id and not current_user.is_admin:
        flash('삭제 권한이 없습니다.', 'error')
        return redirect(url_for('votes.view', vote_id=vote_id))

    db.session.delete(vote)
    db.session.commit()

    flash('투표가 삭제되었습니다.', 'success')
    return redirect(url_for('votes.list'))
