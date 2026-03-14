"""이메일 발송 유틸리티"""
from flask import url_for, current_app
from flask_mail import Message


VERIFY_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Noto Sans KR',sans-serif;">
<div style="max-width:560px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="background:#C1121F;padding:32px 24px;text-align:center;">
        <h1 style="color:#fff;font-size:28px;font-weight:700;margin:0;">NR2 Network</h1>
        <p style="color:rgba(255,255,255,0.8);font-size:13px;margin:8px 0 0;">이메일 인증</p>
    </div>
    <div style="padding:32px 24px;">
        <h2 style="font-size:20px;color:#1a1a1a;margin:0 0 16px;">{{ nickname }}님, 환영합니다!</h2>
        <p style="font-size:15px;color:#555;line-height:1.7;margin:0 0 24px;">
            NR2 Network에 가입해주셔서 감사합니다.<br>
            아래 버튼을 클릭하여 이메일 인증을 완료해주세요.
        </p>
        <div style="text-align:center;margin:32px 0;">
            <a href="{{ verify_url }}"
               style="display:inline-block;padding:14px 40px;background:#C1121F;color:#fff;font-size:16px;font-weight:700;border-radius:8px;text-decoration:none;">
                이메일 인증하기
            </a>
        </div>
        <p style="font-size:12px;color:#999;line-height:1.6;margin:24px 0 0;">
            버튼이 작동하지 않는 경우 아래 링크를 복사하여 브라우저에 붙여넣어주세요:<br>
            <a href="{{ verify_url }}" style="color:#C1121F;word-break:break-all;">{{ verify_url }}</a>
        </p>
    </div>
    <div style="background:#f9f9f9;padding:16px 24px;text-align:center;">
        <p style="font-size:11px;color:#bbb;margin:0;">&copy; 2026 NR2 Network</p>
    </div>
</div>
</body>
</html>
"""


def send_verification_email(user):
    """이메일 인증 링크 발송. SMTP 미설정 시 False 반환."""
    from app import mail

    if not current_app.config.get('MAIL_USERNAME'):
        current_app.logger.warning('MAIL_USERNAME 미설정 — 이메일 발송 건너뜀')
        return False

    token = user.email_verify_token
    verify_url = url_for('auth.verify_email', token=token, _external=True)

    # Jinja2로 렌더링
    from jinja2 import Template
    html_body = Template(VERIFY_EMAIL_TEMPLATE).render(
        nickname=user.nickname,
        verify_url=verify_url
    )

    msg = Message(
        subject='[NR2 Network] 이메일 인증을 완료해주세요',
        recipients=[user.email],
    )
    msg.html = html_body

    try:
        mail.send(msg)
        current_app.logger.info(f'인증 메일 발송 완료: {user.email}')
        return True
    except Exception as e:
        current_app.logger.error(f'인증 메일 발송 실패: {e}')
        return False
