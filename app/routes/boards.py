import os
import re
import bleach
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db

# Quill 에디터 HTML 허용 태그/속성
ALLOWED_TAGS = [
    'p', 'br', 'span', 'div',
    'strong', 'em', 'u', 's',
    'h1', 'h2', 'h3', 'h4',
    'ul', 'ol', 'li',
    'blockquote', 'pre', 'code',
    'a', 'img', 'iframe',
]
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'style'],
    'a': ['href', 'target', 'rel'],
    'img': ['src', 'alt', 'width', 'height', 'class'],
    'iframe': ['src', 'width', 'height', 'frameborder',
               'allowfullscreen', 'allow'],
}

def sanitize_html(html_content):
    """Quill 에디터 HTML을 안전하게 정제"""
    if not html_content:
        return html_content
    return bleach.clean(
        html_content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
    )
from app.utils.telegram_notify import notify_new_post
from app.models import Post, PostImage, Comment, Like, PostVote, User

bp = Blueprint('boards', __name__, url_prefix='/boards')

# 게시판 이름 매핑
BOARD_NAMES = {
    'free': '자유게시판',
    'left': 'LEFT로 가세요',
    'right': 'RIGHT로 가세요',
    'fakenews': '팩트체크',
    'morpheus': '모피어스뉴스',
    'aesa': '누렁이 AESA',
    # 직군별 라운지
    'lounge_media': '언론인 라운지',
    'lounge_congress': '국회 라운지',
    'lounge_govt': '정부 라운지',
    'lounge_corp': '기업 라운지',
    'lounge_public': '행인 광장',
    'lounge_bamboo': '누렁이 대나무숲',
    'pick': '누렁이 픽',
}

# 일반 회원이 글 작성 가능한 게시판 (나머지는 관리자 전용)
USER_WRITABLE_BOARDS = ['free', 'left', 'right', 'pick',
                        'lounge_media', 'lounge_congress', 'lounge_govt',
                        'lounge_corp', 'lounge_public', 'lounge_bamboo']

# 라운지 게시판: board_type → 필요한 job_category (None = 전체 로그인 유저)
LOUNGE_BOARDS = {
    'lounge_media': 'media',
    'lounge_congress': 'congress',
    'lounge_govt': 'govt',
    'lounge_corp': 'corp',
    'lounge_public': None,    # 전체 로그인 회원
    'lounge_bamboo': None,    # 전체 로그인 회원
}

# 라운지 뱃지 매핑
LOUNGE_BADGES = {
    'lounge_media': '익명·언론인',
    'lounge_congress': '익명·국회',
    'lounge_govt': '익명·정부',
    'lounge_corp': '익명·기업',
    'lounge_public': '익명·행인',
    'lounge_bamboo': '익명',
}

# 직군 한글 매핑
JOB_CATEGORY_NAMES = {
    'media': '언론인',
    'congress': '국회',
    'govt': '정부',
    'corp': '기업',
    'public': '행인',
}

# 라운지 배경 이미지 매핑
LOUNGE_IMAGES = {
    'lounge_media': 'lounge/media.png',
    'lounge_congress': 'lounge/congress.png',
    'lounge_govt': 'lounge/govt.png',
    'lounge_corp': 'lounge/corp.jpg',
    'lounge_public': 'lounge/public.png',
    'lounge_bamboo': 'lounge/bamboo.png',
}

def _is_lounge_board(board_type):
    return board_type in LOUNGE_BOARDS

def _check_lounge_access(board_type):
    """라운지 접근 권한 확인. 접근 가능하면 True, 아니면 False."""
    if board_type not in LOUNGE_BOARDS:
        return True
    if not current_user.is_authenticated:
        return False
    if current_user.is_admin or current_user.is_vice_admin:
        return True
    required = LOUNGE_BOARDS[board_type]
    if required is None:
        return True  # 전체 로그인 유저 접근 가능
    return current_user.job_category == required


def extract_youtube_id(url):
    """유튜브 URL에서 영상 ID 추출"""
    if not url:
        return None
    pattern = r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

VALID_BOARDS = list(BOARD_NAMES.keys())


def allowed_file(filename):
    """허용된 파일 확장자 확인"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def save_upload_file(file):
    """업로드된 파일 저장 - Cloudinary 연동"""
    if file and allowed_file(file.filename):
        from app.utils.image_processing import save_upload_image
        image_url = save_upload_image(file, None, prefix='post')
        return image_url
    return None


@bp.route('/<board_type>')
def board(board_type):
    """게시판 목록"""
    # 게시판 타입 검증
    if board_type not in VALID_BOARDS:
        flash('존재하지 않는 게시판입니다.', 'error')
        return redirect(url_for('main.index'))

    # 라운지 접근 제어 (비로그인: 목록은 보이되 글쓰기 제한)
    is_lounge = _is_lounge_board(board_type)
    has_access = _check_lounge_access(board_type)

    if is_lounge and not current_user.is_authenticated:
        # 비로그인: 목록은 보여주되 글 내용 클릭 시 로그인 유도
        pass
    elif is_lounge and not has_access:
        required = LOUNGE_BOARDS[board_type]
        job_name = JOB_CATEGORY_NAMES.get(required, required)
        flash(f'해당 직군 인증 회원만 접근 가능합니다. (필요 직군: {job_name})', 'warning')
        return redirect(url_for('boards.lounge_hub'))

    # 페이지 번호 가져오기 (기본값: 1)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('POSTS_PER_PAGE', 20)

    # 검색 파라미터
    search_query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')  # all, title, content, author

    # 기본 쿼리
    query = Post.query.filter_by(board_type=board_type)

    # 검색 적용 (라운지에서는 작성자 검색 비활성화 — 익명)
    if search_query:
        if search_type == 'title':
            query = query.filter(Post.title.contains(search_query))
        elif search_type == 'content':
            query = query.filter(Post.content.contains(search_query))
        elif search_type == 'author' and not is_lounge:
            query = query.join(User).filter(User.nickname.contains(search_query))
        else:  # all
            if is_lounge:
                query = query.filter(
                    db.or_(
                        Post.title.contains(search_query),
                        Post.content.contains(search_query),
                    )
                )
            else:
                query = query.join(User).filter(
                    db.or_(
                        Post.title.contains(search_query),
                        Post.content.contains(search_query),
                        User.nickname.contains(search_query)
                    )
                )

    # 정렬 및 페이지네이션
    pagination = query.order_by(Post.created_at.desc())\
                      .paginate(page=page, per_page=per_page, error_out=False)

    posts = pagination.items

    return render_template('boards/list.html',
                         board_type=board_type,
                         board_name=BOARD_NAMES[board_type],
                         posts=posts,
                         pagination=pagination,
                         search_query=search_query,
                         search_type=search_type,
                         is_lounge=is_lounge,
                         has_access=has_access,
                         lounge_badge=LOUNGE_BADGES.get(board_type, ''),
                         lounge_image=LOUNGE_IMAGES.get(board_type, ''))


@bp.route('/lounge')
def lounge_hub():
    """라운지 허브 — 자유게시판 + 직군별 게시판 통합"""
    boards = []
    # 자유게시판을 첫 번째로 추가
    boards.append({
        'board_type': 'free',
        'name': '자유게시판',
        'badge': '전체',
        'required_job': None,
        'job_name': '전체',
        'has_access': True,
        'count': Post.query.filter_by(board_type='free').count(),
        'image': '',
        'description': '누구나 자유롭게 대화하는 열린 게시판',
    })
    for bt, name in BOARD_NAMES.items():
        if bt in LOUNGE_BOARDS:
            boards.append({
                'board_type': bt,
                'name': name,
                'badge': LOUNGE_BADGES[bt],
                'required_job': LOUNGE_BOARDS[bt],
                'job_name': JOB_CATEGORY_NAMES.get(LOUNGE_BOARDS[bt], '전체'),
                'has_access': _check_lounge_access(bt),
                'count': Post.query.filter_by(board_type=bt).count(),
                'image': LOUNGE_IMAGES.get(bt, ''),
            })
    return render_template('boards/lounge_hub.html', boards=boards)


@bp.route('/<board_type>/write', methods=['GET', 'POST'])
@login_required
def write(board_type):
    """게시글 작성"""
    # 게시판 타입 검증
    if board_type not in VALID_BOARDS:
        flash('존재하지 않는 게시판입니다.', 'error')
        return redirect(url_for('main.index'))

    # 라운지 접근 제어
    if _is_lounge_board(board_type) and not _check_lounge_access(board_type):
        flash('해당 직군 인증 회원만 글을 작성할 수 있습니다.', 'warning')
        return redirect(url_for('boards.board', board_type=board_type))

    # 글쓰기 권한 체크: 일반 회원은 free/left/right + 라운지만 가능
    if board_type not in USER_WRITABLE_BOARDS and not (current_user.is_admin or current_user.is_vice_admin):
        flash('해당 게시판은 관리자만 글을 작성할 수 있습니다.', 'error')
        return redirect(url_for('boards.board', board_type=board_type))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = sanitize_html(request.form.get('content', '').strip())
        youtube_url = request.form.get('youtube_url', '').strip() or None
        external_url = request.form.get('external_url', '').strip() or None
        og_image_url = request.form.get('og_image', '').strip() or None

        # 유효성 검사
        errors = []
        if not title:
            errors.append('제목을 입력해주세요.')
        elif len(title) > 200:
            errors.append('제목은 200자를 초과할 수 없습니다.')

        if not content:
            errors.append('내용을 입력해주세요.')

        if youtube_url and not extract_youtube_id(youtube_url):
            errors.append('유효한 유튜브 URL을 입력해주세요.')

        if board_type == 'pick' and not external_url:
            errors.append('누렁이 픽은 URL을 입력해야 합니다.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('boards/write.html',
                                 board_type=board_type,
                                 board_name=BOARD_NAMES[board_type],
                                 title=title,
                                 content=content,
                                 youtube_url=youtube_url or '',
                                 external_url=external_url or '',
                                 og_image=og_image_url or '')

        # 게시글 생성
        post = Post(
            title=title,
            content=content,
            board_type=board_type,
            youtube_url=youtube_url,
            external_url=external_url,
            og_image=og_image_url,
            user_id=current_user.id
        )
        db.session.add(post)
        db.session.flush()  # post.id를 얻기 위해

        # 이미지 업로드 처리
        uploaded_files = request.files.getlist('images')
        uploaded_count = 0

        for idx, file in enumerate(uploaded_files):
            if file and file.filename:
                if uploaded_count >= 5:
                    flash('이미지는 최대 5개까지 업로드할 수 있습니다.', 'warning')
                    break

                filename = save_upload_file(file)
                if filename:
                    post_image = PostImage(
                        filename=filename,
                        order=uploaded_count,
                        post_id=post.id
                    )
                    db.session.add(post_image)
                    uploaded_count += 1
                else:
                    flash(f'"{file.filename}"은(는) 허용되지 않는 파일 형식입니다.', 'warning')

        db.session.commit()

        # 텔레그램 알림 (모든 게시판)
        try:
            import logging
            logging.getLogger(__name__).info(f"[텔레그램] 새 글 전송: id={post.id}, board_type={board_type}")
            notify_new_post(post)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[텔레그램] 전송 실패: {e}")

        # NP 적립
        from app.models.np_point import award_np
        np_earned = award_np(current_user, 'post_write')
        db.session.commit()

        if np_earned:
            flash(f'게시글이 작성되었습니다. +{np_earned} NP 적립!', 'success')
        else:
            flash('게시글이 작성되었습니다.', 'success')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post.id))

    return render_template('boards/write.html',
                         board_type=board_type,
                         board_name=BOARD_NAMES[board_type])


@bp.route('/<board_type>/<int:post_id>')
def view(board_type, post_id):
    """게시글 조회"""
    post = Post.query.get_or_404(post_id)

    # 게시판 타입 확인
    if post.board_type != board_type:
        return redirect(url_for('boards.view', board_type=post.board_type, post_id=post_id))

    # 조회수 증가
    post.increment_views()

    youtube_embed_url = None
    youtube_id = extract_youtube_id(post.youtube_url)
    if youtube_id:
        youtube_embed_url = f'https://www.youtube.com/embed/{youtube_id}'

    # 추천/비추천 데이터
    up_count = PostVote.query.filter_by(post_id=post.id, vote_type='up').count()
    down_count = PostVote.query.filter_by(post_id=post.id, vote_type='down').count()
    user_vote = None
    if current_user.is_authenticated:
        vote = PostVote.query.filter_by(post_id=post.id, user_id=current_user.id).first()
        user_vote = vote.vote_type if vote else None

    is_lounge = _is_lounge_board(board_type)

    # 라운지 비로그인 접근 시 로그인 유도
    if is_lounge and not current_user.is_authenticated:
        flash('라운지 게시물을 보려면 로그인이 필요합니다.', 'warning')
        return redirect(url_for('auth.login'))

    # 라운지 직군 제한 (대나무숲/행인광장 제외)
    if is_lounge and not _check_lounge_access(board_type):
        flash('해당 직군 인증 회원만 접근 가능합니다.', 'warning')
        return redirect(url_for('boards.lounge_hub'))

    return render_template('boards/view.html', post=post, youtube_embed_url=youtube_embed_url,
                           up_count=up_count, down_count=down_count, user_vote=user_vote,
                           board_name=BOARD_NAMES.get(board_type, board_type),
                           is_lounge=is_lounge,
                           lounge_badge=LOUNGE_BADGES.get(board_type, ''),
                         lounge_image=LOUNGE_IMAGES.get(board_type, ''))


@bp.route('/<board_type>/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(board_type, post_id):
    """게시글 수정"""
    post = Post.query.get_or_404(post_id)

    # 게시판 타입 확인
    if post.board_type != board_type:
        return redirect(url_for('boards.edit', board_type=post.board_type, post_id=post_id))

    # 권한 확인 (작성자 또는 관리자/부방장만)
    if post.user_id != current_user.id and not (current_user.is_admin or current_user.is_vice_admin):
        flash('수정 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = sanitize_html(request.form.get('content', '').strip())
        youtube_url = request.form.get('youtube_url', '').strip() or None

        # 유효성 검사
        errors = []
        if not title:
            errors.append('제목을 입력해주세요.')
        elif len(title) > 200:
            errors.append('제목은 200자를 초과할 수 없습니다.')

        if not content:
            errors.append('내용을 입력해주세요.')

        if youtube_url and not extract_youtube_id(youtube_url):
            errors.append('유효한 유튜브 URL을 입력해주세요.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('boards/edit.html',
                                 post=post,
                                 board_type=board_type,
                                 board_name=BOARD_NAMES[board_type])

        # 게시글 수정
        post.title = title
        post.content = content
        post.youtube_url = youtube_url

        # 기존 이미지 삭제 여부 처리
        delete_images = request.form.getlist('delete_images')
        for image_id in delete_images:
            image = PostImage.query.get(int(image_id))
            if image and image.post_id == post.id:
                # 파일 삭제
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], image.filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                db.session.delete(image)

        # 새 이미지 업로드
        uploaded_files = request.files.getlist('images')
        current_image_count = post.images.count()

        for file in uploaded_files:
            if file and file.filename:
                if current_image_count >= 5:
                    flash('이미지는 최대 5개까지 업로드할 수 있습니다.', 'warning')
                    break

                filename = save_upload_file(file)
                if filename:
                    post_image = PostImage(
                        filename=filename,
                        order=current_image_count,
                        post_id=post.id
                    )
                    db.session.add(post_image)
                    current_image_count += 1

        db.session.commit()
        flash('게시글이 수정되었습니다.', 'success')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    return render_template('boards/edit.html',
                         post=post,
                         board_type=board_type,
                         board_name=BOARD_NAMES[board_type])


@bp.route('/<board_type>/<int:post_id>/delete', methods=['GET', 'POST'])
@login_required
def delete_post(board_type, post_id):
    """게시글 삭제"""
    current_app.logger.info(f'[DELETE] 삭제 요청: board={board_type}, post={post_id}, user={current_user.id}, method={request.method}')

    post = Post.query.get_or_404(post_id)

    # 권한 확인 (작성자 또는 관리자/부방장만)
    if post.user_id != current_user.id and not current_user.is_admin and not getattr(current_user, 'is_vice_admin', False):
        current_app.logger.warning(f'[DELETE] 권한 없음: post.user_id={post.user_id}, current_user={current_user.id}')
        flash('권한이 없습니다.', 'error')
        return redirect(url_for('boards.board', board_type=board_type))

    try:
        # 이미지 파일 삭제
        for image in post.images:
            try:
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], image.filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass

        db.session.delete(post)
        db.session.commit()
        current_app.logger.info(f'[DELETE] 삭제 성공: post_id={post_id}')
        flash('게시글이 삭제되었습니다.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'[DELETE] 삭제 실패: {e}')
        flash(f'삭제 중 오류: {str(e)}', 'error')

    return redirect(url_for('boards.board', board_type=board_type))


# ===== 댓글 관련 라우트 =====

@bp.route('/<board_type>/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(board_type, post_id):
    """댓글 작성"""
    post = Post.query.get_or_404(post_id)

    content = request.form.get('content', '').strip()
    parent_id = request.form.get('parent_id', type=int)

    # 유효성 검사
    if not content:
        flash('댓글 내용을 입력해주세요.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    # 대댓글인 경우 부모 댓글 확인
    if parent_id:
        parent_comment = Comment.query.get(parent_id)
        if not parent_comment or parent_comment.post_id != post_id:
            flash('잘못된 요청입니다.', 'error')
            return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    # 댓글 생성
    comment = Comment(
        content=content,
        user_id=current_user.id,
        post_id=post_id,
        parent_id=parent_id
    )
    db.session.add(comment)

    # NP 적립
    from app.models.np_point import award_np
    np_earned = award_np(current_user, 'comment_write')
    db.session.commit()

    if np_earned:
        flash(f'댓글이 작성되었습니다. +{np_earned} NP 적립!', 'success')
    else:
        flash('댓글이 작성되었습니다.', 'success')
    return redirect(url_for('boards.view', board_type=board_type, post_id=post_id) + f'#comment-{comment.id}')


@bp.route('/<board_type>/<int:post_id>/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(board_type, post_id, comment_id):
    """댓글 수정"""
    comment = Comment.query.get_or_404(comment_id)

    # 권한 확인 (작성자 또는 관리자/부방장만)
    if comment.user_id != current_user.id and not (current_user.is_admin or current_user.is_vice_admin):
        flash('수정 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    content = request.form.get('content', '').strip()

    if not content:
        flash('댓글 내용을 입력해주세요.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    comment.content = content
    db.session.commit()

    flash('댓글이 수정되었습니다.', 'success')
    return redirect(url_for('boards.view', board_type=board_type, post_id=post_id) + f'#comment-{comment.id}')


@bp.route('/<board_type>/<int:post_id>/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(board_type, post_id, comment_id):
    """댓글 삭제"""
    comment = Comment.query.get_or_404(comment_id)

    # 권한 확인 (작성자 또는 관리자/부방장만)
    if comment.user_id != current_user.id and not current_user.is_admin and not getattr(current_user, 'is_vice_admin', False):
        flash('삭제 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    # 댓글 삭제 (cascade로 대댓글도 자동 삭제)
    try:
        db.session.delete(comment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'댓글 삭제 실패: {e}')
        flash('삭제 중 오류가 발생했습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    flash('댓글이 삭제되었습니다.', 'success')
    return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))


# ===== 좋아요 관련 라우트 =====

@bp.route('/<board_type>/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(board_type, post_id):
    """좋아요 토글 (AJAX)"""
    post = Post.query.get_or_404(post_id)

    # 기존 좋아요 확인
    existing_like = Like.query.filter_by(
        user_id=current_user.id,
        post_id=post_id
    ).first()

    if existing_like:
        # 좋아요 취소
        db.session.delete(existing_like)
        db.session.commit()
        liked = False
    else:
        # 좋아요 추가
        new_like = Like(
            user_id=current_user.id,
            post_id=post_id
        )
        db.session.add(new_like)
        db.session.commit()
        liked = True

    # 현재 좋아요 개수
    likes_count = post.likes_count

    return jsonify({
        'success': True,
        'liked': liked,
        'likes_count': likes_count
    })


# ===== 추천/비추천 관련 라우트 =====

@bp.route('/post/<int:post_id>/vote', methods=['POST'])
@login_required
def vote_post(post_id):
    """게시글 추천/비추천 (AJAX)"""
    post = Post.query.get_or_404(post_id)

    # 공지글은 추천/비추천 불가
    if post.board_type == 'notice':
        return jsonify({'error': '공지글은 투표할 수 없습니다'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': '잘못된 요청'}), 400

    vote_type = data.get('vote_type')
    if vote_type not in ['up', 'down']:
        return jsonify({'error': '잘못된 요청'}), 400

    existing = PostVote.query.filter_by(
        post_id=post_id,
        user_id=current_user.id
    ).first()

    if existing:
        if existing.vote_type == vote_type:
            # 같은 버튼 재클릭 → 취소
            db.session.delete(existing)
            db.session.commit()
            action = 'cancelled'
        else:
            # 반대 버튼 클릭 → 변경
            existing.vote_type = vote_type
            db.session.commit()
            action = 'changed'
    else:
        # 신규 투표
        vote = PostVote(
            post_id=post_id,
            user_id=current_user.id,
            vote_type=vote_type
        )
        db.session.add(vote)
        db.session.commit()
        action = 'voted'

    up_count = PostVote.query.filter_by(post_id=post_id, vote_type='up').count()
    down_count = PostVote.query.filter_by(post_id=post_id, vote_type='down').count()

    # 추천 10개 돌파 시 글쓴이에게 NP 보너스
    np_msg = ''
    if up_count == 10 and vote_type == 'up' and action == 'voted':
        from app.models.np_point import award_np, PointHistory
        already = PointHistory.query.filter_by(
            user_id=post.user_id, action_type='post_likes_10',
            description=f'글 추천 10개 돌파 (#{post.id})'
        ).first()
        if not already:
            post_author = User.query.get(post.user_id)
            if post_author:
                award_np(post_author, 'post_likes_10', f'글 추천 10개 돌파 (#{post.id})')
                db.session.commit()

    return jsonify({
        'action': action,
        'up_count': up_count,
        'down_count': down_count,
        'user_vote': vote_type if action != 'cancelled' else None
    })


# ──────────────────────────────────────────────
# OG 태그 파싱 API (누렁이 픽용)
# ──────────────────────────────────────────────

@bp.route('/api/parse-og', methods=['POST'])
@login_required
def parse_og():
    """URL에서 og:title, og:image 파싱"""
    url = request.json.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL을 입력해주세요.'}), 400

    # 유튜브 썸네일 자동 추출
    yt_id = extract_youtube_id(url)
    if yt_id:
        return jsonify({
            'title': '',  # 유튜브 제목은 클라이언트에서 수동 입력
            'image': f'https://img.youtube.com/vi/{yt_id}/mqdefault.jpg',
            'domain': 'youtube.com',
        })

    import requests as req
    try:
        resp = req.get(url, timeout=8, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; NR2Bot/1.0; +https://nr2.kr)'
        })
        resp.raise_for_status()
        html = resp.text[:50000]  # 앞부분만 파싱

        og_title = ''
        og_image = ''

        # og:title
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html, re.I)
        if m:
            og_title = m.group(1).strip()

        # og:image
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
        if m:
            og_image = m.group(1).strip()

        # fallback: <title>
        if not og_title:
            m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
            if m:
                og_title = m.group(1).strip()

        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace('www.', '')

        return jsonify({
            'title': og_title,
            'image': og_image,
            'domain': domain,
        })
    except Exception as e:
        return jsonify({'error': f'파싱 실패: {str(e)}'}), 400
