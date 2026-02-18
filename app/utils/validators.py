"""입력 유효성 검사 유틸리티"""
import re
from flask import current_app
from markupsafe import Markup, escape


def validate_password_strength(password):
    """
    비밀번호 강도 검사

    Requirements:
    - 최소 6자

    Returns:
        (is_valid, message): 유효성 여부와 메시지
    """
    if len(password) < 6:
        return False, "비밀번호는 최소 6자 이상이어야 합니다."

    return True, "비밀번호가 유효합니다."


def sanitize_html(text):
    """
    XSS 방지를 위한 HTML 이스케이프

    Args:
        text: 입력 텍스트

    Returns:
        이스케이프된 안전한 텍스트
    """
    if not text:
        return text

    # HTML 특수 문자 이스케이프
    return escape(text)


def validate_email_format(email):
    """
    이메일 형식 검사

    Args:
        email: 이메일 주소

    Returns:
        bool: 유효성 여부
    """
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email) is not None


def validate_nickname(nickname):
    """
    닉네임 유효성 검사

    Requirements:
    - 2-50자
    - 한글, 영문, 숫자만 허용

    Returns:
        (is_valid, message): 유효성 여부와 메시지
    """
    if not nickname or len(nickname) < 2:
        return False, "닉네임은 최소 2자 이상이어야 합니다."

    if len(nickname) > 50:
        return False, "닉네임은 최대 50자까지 가능합니다."

    # 한글, 영문, 숫자, 특수문자 허용
    if not re.match(r'^[가-힣a-zA-Z0-9()!@#$%^&*\-_+=\[\]{}<>?./,~]+$', nickname):
        return False, "닉네임에 사용할 수 없는 문자가 포함되어 있습니다."

    return True, "닉네임이 유효합니다."


def validate_file_extension(filename, allowed_extensions=None):
    """
    파일 확장자 검사

    Args:
        filename: 파일명
        allowed_extensions: 허용된 확장자 set

    Returns:
        bool: 유효성 여부
    """
    if allowed_extensions is None:
        allowed_extensions = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif'})

    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions
