from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from email_validator import validate_email, EmailNotValidError
from werkzeug.utils import secure_filename
import os
from app import db
from app.models import User, LoginAttempt
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

        # Create new user
        user = User(email=email, nickname=nickname)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f'{user.nickname}님, 환영합니다!', 'success')
        return redirect(url_for('main.index'))

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

        # Login user
        login_user(user, remember=remember)
        flash(f'{user.nickname}님, 환영합니다!', 'success')

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


@bp.route('/profile')
@login_required
def profile():
    """프로필 페이지"""
    return render_template('auth/profile.html')


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
        # Delete old profile image if it's not the default
        if current_user.profile_image and current_user.profile_image != 'default_profile.jpeg':
            old_image_path = os.path.join('app/static/uploads/profiles', current_user.profile_image)
            if os.path.exists(old_image_path):
                os.remove(old_image_path)

        # Save new image
        filename = secure_filename(f"profile_{current_user.id}_{file.filename}")
        filepath = os.path.join('app/static/uploads/profiles', filename)
        file.save(filepath)

        # Update user profile
        current_user.profile_image = filename
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
