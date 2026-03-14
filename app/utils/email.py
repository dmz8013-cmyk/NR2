"""이메일 발송 유틸리티"""
from flask import url_for, current_app
from flask_mail import Message


def send_verification_email(user):
    """이메일 인증 링크 발송."""
    from app import mail

    token = user.email_verify_token
    verify_url = url_for('auth.verify_email', token=token, _external=True)

    msg = Message(
        subject='[NR2 Network] 이메일 인증을 완료해주세요',
        recipients=[user.email],
        html=f"""
        <div style="font-family:'Noto Sans KR',sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;">
          <div style="text-align:center;margin-bottom:24px;">
            <img src="https://nr2.kr/static/images/nureongi.jpg" style="width:64px;height:64px;border-radius:50%;object-fit:cover;">
          </div>
          <h2 style="color:#1A1A2E;text-align:center;margin-bottom:8px;">NR2 Network</h2>
          <p style="color:#444;text-align:center;margin-bottom:24px;">이메일 인증을 완료해주세요</p>
          <p style="color:#333;">안녕하세요!<br>아래 버튼을 클릭하면 인증이 완료됩니다.</p>
          <div style="text-align:center;margin:32px 0;">
            <a href="{verify_url}"
               style="background:#C87941;color:#ffffff;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;display:inline-block;">
              ✅ 이메일 인증하기
            </a>
          </div>
          <p style="color:#888;font-size:13px;text-align:center;">링크는 24시간 후 만료됩니다.</p>
          <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
          <p style="color:#aaa;font-size:12px;text-align:center;">
            NR2 Network 운영팀 · nr2.kr<br>
            본인이 가입하지 않으셨다면 이 메일을 무시해주세요.
          </p>
        </div>
        """
    )

    mail.send(msg)
    current_app.logger.info(f'인증 메일 발송 완료: {user.email}')
