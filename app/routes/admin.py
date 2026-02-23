from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func, desc
from app import db
from app.models import User, Post, Comment, Like, Vote, VoteResponse, Event, BreakingNews
from app.models.briefing import Briefing
from app.models.bias import NewsArticle, BiasVote

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """관리자 권한 확인 데코레이터"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('관리자 권한이 필요합니다.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/')
@admin_required
def dashboard():
    """관리자 대시보드"""
    # 전체 통계
    total_users = User.query.count()
    total_posts = Post.query.count()
    total_comments = Comment.query.count()
    total_likes = Like.query.count()
    total_votes = Vote.query.count()
    total_news = BreakingNews.query.filter_by(is_active=True).count()
    total_briefings = Briefing.query.count()
    today_briefings = Briefing.query.filter(Briefing.created_at >= today_start).count()
    total_bias_articles = NewsArticle.query.count()
    total_bias_votes = BiasVote.query.count()
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    mau = User.query.filter(User.last_login >= thirty_days_ago).count() if hasattr(User, 'last_login') else 0

    # 오늘 통계
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    today_users = User.query.filter(User.created_at >= today_start).count()
    today_posts = Post.query.filter(Post.created_at >= today_start).count()
    today_comments = Comment.query.filter(Comment.created_at >= today_start).count()

    # 최근 7일 통계 (차트용)
    chart_data = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        date_start = datetime.combine(date, datetime.min.time())
        date_end = datetime.combine(date, datetime.max.time())

        posts_count = Post.query.filter(
            Post.created_at >= date_start,
            Post.created_at <= date_end
        ).count()

        chart_data.append({
            'date': date.strftime('%m/%d'),
            'posts': posts_count
        })

    # 인기 게시글 (조회수 기준)
    popular_posts = Post.query.order_by(desc(Post.views)).limit(5).all()

    # 최근 회원가입
    recent_users = User.query.order_by(desc(User.created_at)).limit(5).all()

    # 게시판별 통계
    board_stats = db.session.query(
        Post.board_type,
        func.count(Post.id).label('count')
    ).group_by(Post.board_type).all()

    return render_template('admin/dashboard.html',
                          total_users=total_users,
                          total_posts=total_posts,
                          total_comments=total_comments,
                          total_likes=total_likes,
                          total_votes=total_votes,
                          total_news=total_news,
                          today_users=today_users,
                          today_posts=today_posts,
                          today_comments=today_comments,
                          chart_data=chart_data,
                          popular_posts=popular_posts,
                          recent_users=recent_users,
                          board_stats=board_stats,
                          total_briefings=total_briefings,
                          today_briefings=today_briefings,
                          total_bias_articles=total_bias_articles,
                          total_bias_votes=total_bias_votes,
                          mau=mau)


@bp.route('/users')
@admin_required
def users():
    """회원 관리"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = 20

    query = User.query

    # 검색
    if search:
        query = query.filter(
            (User.email.like(f'%{search}%')) |
            (User.nickname.like(f'%{search}%'))
        )

    pagination = query.order_by(desc(User.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/users.html',
                          users=pagination.items,
                          pagination=pagination,
                          search=search)


@bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    """관리자 권한 토글"""
    user = User.query.get_or_404(user_id)

    # 자기 자신은 변경 불가
    if user.id == current_user.id:
        flash('자신의 권한은 변경할 수 없습니다.', 'error')
        return redirect(url_for('admin.users'))

    user.is_admin = not user.is_admin
    db.session.commit()

    status = '관리자' if user.is_admin else '일반 사용자'
    flash(f'{user.nickname}님의 권한이 {status}로 변경되었습니다.', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """회원 삭제"""
    user = User.query.get_or_404(user_id)

    # 자기 자신은 삭제 불가
    if user.id == current_user.id:
        flash('자신의 계정은 삭제할 수 없습니다.', 'error')
        return redirect(url_for('admin.users'))

    nickname = user.nickname
    db.session.delete(user)
    db.session.commit()

    flash(f'{nickname}님의 계정이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/posts')
@admin_required
def posts():
    """게시글 관리"""
    page = request.args.get('page', 1, type=int)
    board_type = request.args.get('board', '')
    search = request.args.get('search', '')
    per_page = 20

    query = Post.query

    # 게시판 필터
    if board_type:
        query = query.filter_by(board_type=board_type)

    # 검색
    if search:
        query = query.filter(
            (Post.title.like(f'%{search}%')) |
            (Post.content.like(f'%{search}%'))
        )

    pagination = query.order_by(desc(Post.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/posts.html',
                          posts=pagination.items,
                          pagination=pagination,
                          board_type=board_type,
                          search=search)


@bp.route('/posts/<int:post_id>/delete', methods=['POST'])
@admin_required
def delete_post(post_id):
    """게시글 삭제"""
    post = Post.query.get_or_404(post_id)

    title = post.title
    db.session.delete(post)
    db.session.commit()

    flash(f'게시글 "{title}"이(가) 삭제되었습니다.', 'success')
    return redirect(url_for('admin.posts'))


@bp.route('/comments')
@admin_required
def comments():
    """댓글 관리"""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = 20

    query = Comment.query

    # 검색
    if search:
        query = query.filter(Comment.content.like(f'%{search}%'))

    pagination = query.order_by(desc(Comment.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/comments.html',
                          comments=pagination.items,
                          pagination=pagination,
                          search=search)


@bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
@admin_required
def delete_comment(comment_id):
    """댓글 삭제"""
    comment = Comment.query.get_or_404(comment_id)

    db.session.delete(comment)
    db.session.commit()

    flash('댓글이 삭제되었습니다.', 'success')
    return redirect(url_for('admin.comments'))


@bp.route('/votes')
@admin_required
def votes():
    """투표 관리"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    pagination = Vote.query.order_by(desc(Vote.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin/votes.html',
                          votes=pagination.items,
                          pagination=pagination)


@bp.route('/votes/<int:vote_id>/delete', methods=['POST'])
@admin_required
def delete_vote(vote_id):
    """투표 삭제"""
    vote = Vote.query.get_or_404(vote_id)

    title = vote.title
    db.session.delete(vote)
    db.session.commit()

    flash(f'투표 "{title}"이(가) 삭제되었습니다.', 'success')
    return redirect(url_for('admin.votes'))


@bp.route('/breaking-news')
@admin_required
def breaking_news():
    """공지 관리"""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    pagination = BreakingNews.query.order_by(
        desc(BreakingNews.priority),
        desc(BreakingNews.created_at)
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin/breaking_news.html',
                          news_list=pagination.items,
                          pagination=pagination)


@bp.route('/statistics')
@admin_required
def statistics():
    """통계 페이지"""
    # 월별 통계 (최근 6개월)
    monthly_stats = []
    for i in range(5, -1, -1):
        date = datetime.utcnow() - timedelta(days=30*i)
        month_start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        if i == 0:
            month_end = datetime.utcnow()
        else:
            next_month = month_start + timedelta(days=32)
            month_end = next_month.replace(day=1) - timedelta(seconds=1)

        posts = Post.query.filter(
            Post.created_at >= month_start,
            Post.created_at <= month_end
        ).count()

        users = User.query.filter(
            User.created_at >= month_start,
            User.created_at <= month_end
        ).count()

        monthly_stats.append({
            'month': month_start.strftime('%Y-%m'),
            'posts': posts,
            'users': users
        })

    # 게시판별 통계
    board_stats = {}
    boards = ['free', 'left', 'right', 'fakenews']
    board_names = {
        'free': '자유정보',
        'left': 'LEFT정보',
        'right': 'RIGHT정보',
        'fakenews': '팩트체크'
    }

    for board in boards:
        count = Post.query.filter_by(board_type=board).count()
        board_stats[board_names[board]] = count

    # 사용자 활동 통계
    top_posters = db.session.query(
        User.nickname,
        func.count(Post.id).label('post_count')
    ).join(Post).group_by(User.id).order_by(desc('post_count')).limit(10).all()

    top_commenters = db.session.query(
        User.nickname,
        func.count(Comment.id).label('comment_count')
    ).join(Comment).group_by(User.id).order_by(desc('comment_count')).limit(10).all()

    return render_template('admin/statistics.html',
                          monthly_stats=monthly_stats,
                          board_stats=board_stats,
                          top_posters=top_posters,
                          top_commenters=top_commenters)
