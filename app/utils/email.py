"""이메일 발송 유틸리티"""
from flask import url_for, current_app
from flask_mail import Message


def _mail_footer():
    return """
          <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
          <p style="color:#aaa;font-size:12px;text-align:center;">
            NR2 Network 운영팀 · nr2.kr<br>
            본인이 요청하지 않으셨다면 이 메일을 무시해주세요.
          </p>
        </div>
    """


def _mail_header(subtitle):
    return f"""
        <div style="font-family:'Noto Sans KR',sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;">
          <div style="text-align:center;margin-bottom:24px;">
            <img src="https://nr2.kr/static/images/nureongi.jpg" style="width:64px;height:64px;border-radius:50%;object-fit:cover;">
          </div>
          <h2 style="color:#1A1A2E;text-align:center;margin-bottom:8px;">NR2 Network</h2>
          <p style="color:#444;text-align:center;margin-bottom:24px;">{subtitle}</p>
    """


def send_verification_email(user):
    """이메일 인증 링크 발송."""
    from app import mail

    token = user.email_verify_token
    verify_url = url_for('auth.verify_email', token=token, _external=True)

    msg = Message(
        subject='[NR2 Network] 이메일 인증을 완료해주세요',
        recipients=[user.email],
        html=f"""
        {_mail_header('이메일 인증을 완료해주세요')}
          <p style="color:#333;">안녕하세요!<br>아래 버튼을 클릭하면 인증이 완료됩니다.</p>
          <div style="text-align:center;margin:32px 0;">
            <a href="{verify_url}"
               style="background:#C87941;color:#ffffff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;display:inline-block;">
              이메일 인증하기
            </a>
          </div>
          <p style="color:#888;font-size:13px;text-align:center;">링크는 24시간 후 만료됩니다.</p>
        {_mail_footer()}
        """
    )

    mail.send(msg)
    current_app.logger.info(f'인증 메일 발송 완료: {user.email}')


def send_password_reset_email(user, token):
    """비밀번호 재설정 링크 발송."""
    from app import mail

    reset_url = url_for('auth.reset_password', token=token, _external=True)

    msg = Message(
        subject='[NR2 Network] 비밀번호 재설정 안내',
        recipients=[user.email],
        html=f"""
        {_mail_header('비밀번호 재설정')}
          <p style="color:#333;">비밀번호 재설정을 요청하셨습니다.<br>아래 버튼을 클릭하여 새 비밀번호를 설정해주세요.</p>
          <div style="text-align:center;margin:32px 0;">
            <a href="{reset_url}"
               style="background:#C87941;color:#ffffff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;display:inline-block;">
              비밀번호 재설정하기
            </a>
          </div>
          <p style="color:#888;font-size:13px;text-align:center;">링크는 1시간 후 만료됩니다.</p>
        {_mail_footer()}
        """
    )

    mail.send(msg)
    current_app.logger.info(f'비밀번호 재설정 메일 발송 완료: {user.email}')
