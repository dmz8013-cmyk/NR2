import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from email_validator import validate_email, EmailNotValidError
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import os
from app import db, oauth
from app.models import User, LoginAttempt
from app.models.post import Post
from app.models.comment import Comment
from app.utils.validators import validate_password_strength, sanitize_html, validate_nickname
from app.utils.image_processing import save_upload_image, delete_image

bp = Blueprint('auth', __name__, url_prefix='/auth')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """회원가입"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        nickname = request.form.get('nickname', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validation
        errors = []

        # Email validation
        if not email:
            errors.append('이메일을 입력해주세요.')
        else:
            try:
                validate_email(email)
            except EmailNotValidError:
                errors.append('유효한 이메일 주소를 입력해주세요.')

            # Check if email already exists
            if User.query.filter_by(email=email).first():
                errors.append('이미 사용 중인 이메일입니다.')

        # Nickname validation
        is_valid_nickname, nickname_msg = validate_nickname(nickname)
        if not is_valid_nickname:
            errors.append(nickname_msg)
        else:
            # Check if nickname already exists
            if User.query.filter_by(nickname=nickname).first():
                errors.append('이미 사용 중인 닉네임입니다.')

        # Password strength validation
        if not password:
            errors.append('비밀번호를 입력해주세요.')
        else:
            is_strong, pwd_msg = validate_password_strength(password)
            if not is_strong:
                errors.append(pwd_msg)

        if password != password_confirm:
            errors.append('비밀번호가 일치하지 않습니다.')

        # If there are errors, show them
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/register.html')

        # 직군 선택
        job_category = request.form.get('job_category', 'public').strip()
        valid_jobs = ['media', 'congress', 'govt', 'corp', 'public']
        if job_category not in valid_jobs:
            job_category = 'public'

        # Create new user
        user = User(email=email, nickname=nickname, job_category=job_category)
        user.set_password(password)
        user.email_verified = False
        user.email_verify_token = secrets.token_urlsafe(32)

        db.session.add(user)
        db.session.flush()

        # NP 가입 보너스
        from app.models.np_point import award_np
        award_np(user, 'signup_bonus')
        db.session.commit()

        # 인증 이메일 발송
        try:
            from app.utils.email import send_verification_email
            send_verification_email(user)
            flash('인증 이메일이 발송되었습니다. 이메일을 확인해주세요.', 'success')
        except Exception as e:
            current_app.logger.error(f'인증 메일 발송 실패: {e}')
            # 발송 실패 시에도 가입은 완료 — 재발송 가능
            flash('가입은 완료되었으나 인증 메일 발송에 실패했습니다. 로그인 후 재발송해주세요.', 'warning')

        login_user(user)

        return redirect(url_for('auth.email_pending'))

    return render_template('auth/register.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """로그인"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False) == 'on'
        ip_address = request.remote_addr

        if not email or not password:
            flash('이메일과 비밀번호를 입력해주세요.', 'error')
            return render_template('auth/login.html')

        # Check if account is locked
        max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS', 5)
        lockout_duration = current_app.config.get('LOCKOUT_DURATION', 1800)

        is_locked, remaining_time = LoginAttempt.is_locked(email, max_attempts, lockout_duration)

        if is_locked:
            minutes = remaining_time // 60
            seconds = remaining_time % 60
            flash(f'로그인 시도 횟수를 초과했습니다. {minutes}분 {seconds}초 후에 다시 시도해주세요.', 'error')
            return render_template('auth/login.html')

        # Find user
        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            # Record failed attempt
            LoginAttempt.record_attempt(email, ip_address, success=False)

            remaining = LoginAttempt.get_remaining_attempts(email, max_attempts, lockout_duration)
            if remaining > 0:
                flash(f'이메일 또는 비밀번호가 잘못되었습니다. (남은 시도: {remaining}회)', 'error')
            else:
                flash('로그인 시도 횟수를 초과했습니다. 30분 후에 다시 시도해주세요.', 'error')

            return render_template('auth/login.html')

        # Record successful attempt
        LoginAttempt.record_attempt(email, ip_address, success=True)

        # 정지 상태 체크
        if user.suspended_until and user.suspended_until > datetime.now():
            remaining = user.suspended_until - datetime.now()
            days = remaining.days
            hours = remaining.seconds // 3600
            flash(f'계정이 정지 중입니다. {days}일 {hours}시간 후 해제됩니다.', 'error')
            return render_template('auth/login.html')

        # Login user
        login_user(user, remember=remember)

        # 연속 접속 체크 + NP 보상
        from datetime import date as date_cls
        from app.models.np_point import award_np
        today = date_cls.today()
        if user.last_login_date != today:
            if user.last_login_date and (today - user.last_login_date).days == 1:
                user.login_streak = (user.login_streak or 0) + 1
            elif user.last_login_date and (today - user.last_login_date).days > 1:
                user.login_streak = 1
            else:
                user.login_streak = (user.login_streak or 0) + 1
            user.last_login_date = today

            if user.login_streak == 7:
                award_np(user, 'weekly_streak')
            elif user.login_streak == 30:
                award_np(user, 'monthly_streak')
                
            db.session.commit()

            from app.utils.badge_service import check_and_award_badges
            check_and_award_badges(user)

        flash(f'{user.nickname}님, 환영합니다!', 'success')

        # 이메일 미인증 시 인증 대기 페이지로
        if not user.email_verified:
            return redirect(url_for('auth.email_pending'))

        # 신규 가입자 온보딩
        if not user.onboarding_completed:
            return redirect(url_for('auth.onboarding'))

        # Redirect to next page or home
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('main.index'))

    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    """로그아웃"""
    logout_user()
    flash('로그아웃되었습니다.', 'info')
    return redirect(url_for('main.index'))


# ── Google OAuth ──────────────────────────────────────────

@bp.route('/google/login')
def google_login():
    """Google 소셜 로그인 시작"""
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route('/google/callback')
def google_callback():
    """Google OAuth 콜백 — 로그인/회원가입 통합 처리"""
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            user_info = oauth.google.userinfo()
    except Exception as e:
        current_app.logger.error(f'Google OAuth 오류: {e}')
        flash('Google 로그인에 실패했습니다. 다시 시도해주세요.', 'error')
        return redirect(url_for('auth.login'))

    google_id = user_info.get('sub')
    email = user_info.get('email')
    name = user_info.get('name', '')
    picture = user_info.get('picture', '')

    if not google_id or not email:
        flash('Google 계정 정보를 가져올 수 없습니다.', 'error')
        return redirect(url_for('auth.login'))

    # 1) google_id로 기존 사용자 검색
    user = User.query.filter_by(google_id=google_id).first()

    # 2) google_id 없으면 이메일로 검색 (기존 이메일 가입자 연동)
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
            db.session.commit()

    # 3) 완전히 새로운 사용자 — 자동 회원가입
    if not user:
        # 닉네임 생성: Google 이름 사용, 중복 시 랜덤 접미사
        base_nickname = name[:20] if name else email.split('@')[0][:20]
        nickname = base_nickname
        suffix = 1
        while User.query.filter_by(nickname=nickname).first():
            nickname = f'{base_nickname}_{suffix}'
            suffix += 1

        user = User(
            email=email,
            nickname=nickname,
            google_id=google_id,
            email_verified=True,  # Google 인증된 이메일
            profile_image=picture or 'default_profile.jpeg',
        )
        # 소셜 로그인은 비밀번호 불필요 — 랜덤 해시 설정
        user.password_hash = generate_password_hash(secrets.token_urlsafe(32))

        db.session.add(user)
        db.session.flush()

        # NP 가입 보너스
        from app.models.np_point import award_np
        award_np(user, 'signup_bonus')
        db.session.commit()

        flash(f'{user.nickname}님, 환영합니다!', 'success')
        login_user(user)
        return redirect(url_for('auth.onboarding'))

    # 기존 사용자 로그인
    if user.suspended_until and user.suspended_until > datetime.now():
        remaining = user.suspended_until - datetime.now()
        flash(f'계정이 정지 중입니다. {remaining.days}일 후 해제됩니다.', 'error')
        return redirect(url_for('auth.login'))

    login_user(user)

    # 연속 접속 체크 + NP 보상
    from datetime import date as date_cls
    from app.models.np_point import award_np
    today = date_cls.today()
    if user.last_login_date != today:
        if user.last_login_date and (today - user.last_login_date).days == 1:
            user.login_streak = (user.login_streak or 0) + 1
        elif user.last_login_date and (today - user.last_login_date).days > 1:
            user.login_streak = 1
        else:
            user.login_streak = (user.login_streak or 0) + 1
        user.last_login_date = today

        if user.login_streak == 7:
            award_np(user, 'weekly_streak')
        elif user.login_streak == 30:
            award_np(user, 'monthly_streak')

        db.session.commit()

        from app.utils.badge_service import check_and_award_badges
        check_and_award_badges(user)

    flash(f'{user.nickname}님, 환영합니다!', 'success')

    if not user.email_verified:
        return redirect(url_for('auth.email_pending'))

    if not user.onboarding_completed:
        return redirect(url_for('auth.onboarding'))

    return redirect(url_for('main.index'))


BOARD_NAMES = {
    'free': '자유게시판', 'left': 'LEFT', 'right': 'RIGHT',
    'fact': '팩트체크', 'morpheus': '모피어스', 'aesa': 'AESA',
}


@bp.route('/profile')
@login_required
def profile():
    """프로필 페이지"""
    tab = request.args.get('tab', 'info')
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('POSTS_PER_PAGE', 20)

    my_posts = None
    my_comments = None
    point_history = []

    if tab == 'posts':
        my_posts = Post.query.filter_by(user_id=current_user.id) \
            .order_by(Post.created_at.desc()) \
            .paginate(page=page, per_page=per_page, error_out=False)
    elif tab == 'comments':
        my_comments = Comment.query.filter_by(user_id=current_user.id) \
            .options(db.joinedload(Comment.post)) \
            .order_by(Comment.created_at.desc()) \
            .paginate(page=page, per_page=per_page, error_out=False)
    else:
        from app.models.np_point import PointHistory
        from app.models.badge import Badge
        all_badges = Badge.query.order_by(Badge.id.asc()).all()
        point_history = PointHistory.query.filter_by(user_id=current_user.id) \
            .order_by(PointHistory.created_at.desc()).limit(20).all()

    return render_template('auth/profile.html',
                           tab=tab,
                           my_posts=my_posts,
                           my_comments=my_comments,
                           board_names=BOARD_NAMES,
                           point_history=point_history,
                           all_badges=all_badges if tab == 'info' else None)


@bp.route('/profile/badge/<int:badge_id>', methods=['POST'])
@login_required
def set_primary_badge(badge_id):
    """대표 뱃지 설정"""
    from app.models.badge import UserBadge
    ub = UserBadge.query.filter_by(user_id=current_user.id, badge_id=badge_id).first()
    if ub:
        UserBadge.query.filter_by(user_id=current_user.id, is_primary=True).update({'is_primary': False})
        ub.is_primary = True
        db.session.commit()
        flash('대표 뱃지가 성공적으로 장착되었습니다.', 'success')
    else:
        flash('유효하지 않은 뱃지입니다.', 'error')
    return redirect(url_for('auth.profile'))


@bp.route('/profile/upload', methods=['POST'])
@login_required
def upload_profile_image():
    """프로필 이미지 업로드"""
    if 'profile_image' not in request.files:
        flash('이미지를 선택해주세요.', 'error')
        return redirect(url_for('auth.profile'))

    file = request.files['profile_image']

    if file.filename == '':
        flash('이미지를 선택해주세요.', 'error')
        return redirect(url_for('auth.profile'))

    if file and allowed_file(file.filename):
        # Delete old profile image from Cloudinary
        if current_user.profile_image and 'cloudinary.com' in str(current_user.profile_image):
            delete_image(current_user.profile_image, None)

        # Upload to Cloudinary
        image_url = save_upload_image(file, None, prefix=f'profile_{current_user.id}')
        if not image_url:
            flash('이미지 업로드에 실패했습니다.', 'error')
            return redirect(url_for('auth.profile'))

        # Update user profile
        current_user.profile_image = image_url
        db.session.commit()

        flash('프로필 이미지가 업데이트되었습니다.', 'success')
    else:
        flash('허용되지 않는 파일 형식입니다. (png, jpg, jpeg, gif만 가능)', 'error')

    return redirect(url_for('auth.profile'))


@bp.route('/profile/nickname', methods=['POST'])
@login_required
def update_nickname():
    """닉네임 변경"""
    new_nickname = request.form.get('nickname', '').strip()
    
    errors = []
    
    # Nickname validation
    if not new_nickname:
        errors.append('닉네임을 입력해주세요.')
    elif len(new_nickname) < 2 or len(new_nickname) > 20:
        errors.append('닉네임은 2~20자여야 합니다.')
    elif new_nickname == current_user.nickname:
        errors.append('현재 닉네임과 동일합니다.')
    elif User.query.filter_by(nickname=new_nickname).first():
        errors.append('이미 사용 중인 닉네임입니다.')
    
    if errors:
        for error in errors:
            flash(error, 'error')
    else:
        old_nickname = current_user.nickname
        current_user.nickname = new_nickname
        db.session.commit()
        flash(f'닉네임이 "{old_nickname}"에서 "{new_nickname}"(으)로 변경되었습니다!', 'success')

    return redirect(url_for('auth.profile'))


VERIFY_CATEGORIES = {
    'congress': '국회',
    'government': '정부',
    'public_org': '공공기관',
    'local_gov': '지자체',
    'party': '정당',
    'media': '언론',
    'pr': '홍보/대관',
    'research': '연구/학계',
    'legal': '법조',
    'citizen': '시민',
}


@bp.route('/profile/verify', methods=['POST'])
@login_required
def request_verify():
    """본인인증 요청 — 카테고리 선택 시 silver 자동 승급"""
    if current_user.verified_at:
        flash('이미 인증이 완료되었습니다.', 'info')
        return redirect(url_for('auth.profile'))

    category = request.form.get('category', '').strip()
    if category not in VERIFY_CATEGORIES:
        flash('올바른 카테고리를 선택해주세요.', 'error')
        return redirect(url_for('auth.profile'))

    from datetime import datetime
    current_user.verify_tier = 'silver'
    current_user.verify_category = category
    current_user.verify_badge = VERIFY_CATEGORIES[category]
    current_user.verified_at = datetime.now()
    db.session.commit()

    flash(f'✅ 본인인증이 완료되었습니다! ({VERIFY_CATEGORIES[category]})', 'success')
    return redirect(url_for('auth.profile'))


@bp.route('/email-pending')
@login_required
def email_pending():
    """이메일 인증 대기 안내 페이지"""
    if current_user.email_verified:
        return redirect(url_for('main.index'))
    return render_template('auth/email_pending.html')


@bp.route('/verify-email/<token>')
def verify_email(token):
    """이메일 인증 처리"""
    user = User.query.filter_by(email_verify_token=token).first()

    if not user:
        flash('유효하지 않은 인증 링크입니다.', 'error')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    user.email_verify_token = None
    db.session.commit()

    flash('이메일 인증이 완료되었습니다!', 'success')

    if current_user.is_authenticated:
        if not current_user.onboarding_completed:
            return redirect(url_for('auth.onboarding'))
        return redirect(url_for('main.index'))
    return redirect(url_for('auth.login'))


@bp.route('/resend-verification')
@login_required
def resend_verification():
    """인증 메일 재발송"""
    if current_user.email_verified:
        flash('이미 인증된 이메일입니다.', 'info')
        return redirect(url_for('auth.profile'))

    # 토큰 갱신
    current_user.email_verify_token = secrets.token_urlsafe(32)
    db.session.commit()

    try:
        from app.utils.email import send_verification_email
        send_verification_email(current_user)
        flash('인증 이메일이 재발송되었습니다.', 'success')
    except Exception as e:
        current_app.logger.error(f'인증 메일 재발송 실패: {e}')
        flash('메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.', 'error')

    return redirect(url_for('auth.email_pending'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """비밀번호 찾기"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        if not email:
            flash('이메일을 입력해주세요.', 'error')
            return render_template('auth/forgot_password.html')

        user = User.query.filter_by(email=email).first()

        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expires = datetime.now() + timedelta(hours=1)
            db.session.commit()

            # 이메일로 재설정 링크 발송
            try:
                from app.utils.email import send_password_reset_email
                send_password_reset_email(user, token)
            except Exception as e:
                current_app.logger.error(f'비밀번호 재설정 메일 발송 실패: {e}')

        # 사용자 존재 여부를 노출하지 않는 안전한 메시지
        flash('가입된 이메일이라면 비밀번호 재설정 링크가 발송되었습니다. 이메일을 확인해주세요.', 'info')

        return render_template('auth/forgot_password.html')

    return render_template('auth/forgot_password.html')


@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """비밀번호 재설정"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.now():
        flash('유효하지 않거나 만료된 재설정 링크입니다.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        errors = []

        if not password:
            errors.append('비밀번호를 입력해주세요.')
        else:
            is_strong, pwd_msg = validate_password_strength(password)
            if not is_strong:
                errors.append(pwd_msg)

        if password != password_confirm:
            errors.append('비밀번호가 일치하지 않습니다.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth/reset_password.html', token=token)

        # Update password and clear token
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()

        flash('비밀번호가 성공적으로 변경되었습니다. 새 비밀번호로 로그인해주세요.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@bp.route('/onboarding')
@login_required
def onboarding():
    """신규 가입자 온보딩 페이지"""
    if current_user.onboarding_completed:
        return redirect(url_for('main.index'))
    return render_template('auth/onboarding.html')


@bp.route('/onboarding/complete', methods=['POST'])
@login_required
def onboarding_complete():
    """온보딩 완료 처리"""
    current_user.onboarding_completed = True
    db.session.commit()
    return redirect(url_for('main.index'))
