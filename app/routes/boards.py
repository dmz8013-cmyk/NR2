import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Post, PostImage, Comment, Like

bp = Blueprint('boards', __name__, url_prefix='/boards')

# 게시판 이름 매핑
BOARD_NAMES = {
    'free': '자유게시판',
    'left': 'LEFT로 가세요',
    'right': 'RIGHT로 가세요',
    'fakenews': '팩트체크',
    'morpheus': '모피어스뉴스'
}

VALID_BOARDS = list(BOARD_NAMES.keys())


def allowed_file(filename):
    """허용된 파일 확장자 확인"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def save_upload_file(file):
    """업로드된 파일 저장"""
    if file and allowed_file(file.filename):
        # 안전한 파일명 생성
        filename = secure_filename(file.filename)

        # 고유한 파일명 생성 (타임스탬프 추가)
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        name, ext = os.path.splitext(filename)
        unique_filename = f"{timestamp}_{name}{ext}"

        # 파일 저장
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        return unique_filename
    return None


@bp.route('/<board_type>')
def board(board_type):
    """게시판 목록"""
    # 게시판 타입 검증
    if board_type not in VALID_BOARDS:
        flash('존재하지 않는 게시판입니다.', 'error')
        return redirect(url_for('main.index'))

    # 페이지 번호 가져오기 (기본값: 1)
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('POSTS_PER_PAGE', 20)

    # 검색 파라미터
    search_query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'all')  # all, title, content, author

    # 기본 쿼리
    query = Post.query.filter_by(board_type=board_type)

    # 검색 적용
    if search_query:
        if search_type == 'title':
            query = query.filter(Post.title.contains(search_query))
        elif search_type == 'content':
            query = query.filter(Post.content.contains(search_query))
        elif search_type == 'author':
            query = query.join(User).filter(User.nickname.contains(search_query))
        else:  # all
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
                         search_type=search_type)


@bp.route('/<board_type>/write', methods=['GET', 'POST'])
@login_required
def write(board_type):
    """게시글 작성"""
    # 게시판 타입 검증
    if board_type not in VALID_BOARDS:
        flash('존재하지 않는 게시판입니다.', 'error')
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        # 유효성 검사
        errors = []
        if not title:
            errors.append('제목을 입력해주세요.')
        elif len(title) > 200:
            errors.append('제목은 200자를 초과할 수 없습니다.')

        if not content:
            errors.append('내용을 입력해주세요.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('boards/write.html',
                                 board_type=board_type,
                                 board_name=BOARD_NAMES[board_type],
                                 title=title,
                                 content=content)

        # 게시글 생성
        post = Post(
            title=title,
            content=content,
            board_type=board_type,
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

    return render_template('boards/view.html', post=post)


@bp.route('/<board_type>/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(board_type, post_id):
    """게시글 수정"""
    post = Post.query.get_or_404(post_id)

    # 게시판 타입 확인
    if post.board_type != board_type:
        return redirect(url_for('boards.edit', board_type=post.board_type, post_id=post_id))

    # 권한 확인 (작성자 또는 관리자만)
    if post.user_id != current_user.id and not current_user.is_admin:
        flash('수정 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()

        # 유효성 검사
        errors = []
        if not title:
            errors.append('제목을 입력해주세요.')
        elif len(title) > 200:
            errors.append('제목은 200자를 초과할 수 없습니다.')

        if not content:
            errors.append('내용을 입력해주세요.')

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


@bp.route('/<board_type>/<int:post_id>/delete', methods=['POST'])
@login_required
def delete(board_type, post_id):
    """게시글 삭제"""
    post = Post.query.get_or_404(post_id)

    # 게시판 타입 확인
    if post.board_type != board_type:
        return redirect(url_for('boards.delete', board_type=post.board_type, post_id=post_id))

    # 권한 확인 (작성자 또는 관리자만)
    if post.user_id != current_user.id and not current_user.is_admin:
        flash('삭제 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    # 이미지 파일 삭제
    for image in post.images:
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], image.filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    # 게시글 삭제 (cascade로 관련 데이터도 자동 삭제)
    db.session.delete(post)
    db.session.commit()

    flash('게시글이 삭제되었습니다.', 'success')
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
    db.session.commit()

    flash('댓글이 작성되었습니다.', 'success')
    return redirect(url_for('boards.view', board_type=board_type, post_id=post_id) + f'#comment-{comment.id}')


@bp.route('/<board_type>/<int:post_id>/comment/<int:comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(board_type, post_id, comment_id):
    """댓글 수정"""
    comment = Comment.query.get_or_404(comment_id)

    # 권한 확인
    if comment.user_id != current_user.id and not current_user.is_admin:
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

    # 권한 확인
    if comment.user_id != current_user.id and not current_user.is_admin:
        flash('삭제 권한이 없습니다.', 'error')
        return redirect(url_for('boards.view', board_type=board_type, post_id=post_id))

    # 댓글 삭제 (cascade로 대댓글도 자동 삭제)
    db.session.delete(comment)
    db.session.commit()

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
