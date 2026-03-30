"""Gmail SMTP 이메일 발송 테스트 스크립트.

사용법:
    python test_email.py <수신자이메일>

.env에 MAIL_USERNAME, MAIL_PASSWORD가 설정되어 있어야 합니다.
"""
import sys
import os
from dotenv import load_dotenv

load_dotenv()

def test_smtp():
    recipient = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('MAIL_USERNAME')
    if not recipient:
        print('사용법: python test_email.py <수신자이메일>')
        sys.exit(1)

    username = os.environ.get('MAIL_USERNAME')
    password = os.environ.get('MAIL_PASSWORD')

    if not username or not password:
        print('오류: .env에 MAIL_USERNAME, MAIL_PASSWORD를 설정해주세요.')
        print(f'  MAIL_USERNAME = {username or "(미설정)"}')
        print(f'  MAIL_PASSWORD = {"설정됨" if password else "(미설정)"}')
        sys.exit(1)

    print(f'SMTP 설정:')
    print(f'  서버: smtp.gmail.com:587 (TLS)')
    print(f'  발신: {username}')
    print(f'  수신: {recipient}')
    print()

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '[NR2 Network] 이메일 발송 테스트'
    msg['From'] = username
    msg['To'] = recipient

    html = """
    <div style="font-family:'Noto Sans KR',sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#fff;">
      <h2 style="color:#1A1A2E;text-align:center;">NR2 Network</h2>
      <p style="color:#333;text-align:center;">Gmail SMTP 이메일 발송 테스트 성공!</p>
      <p style="color:#888;font-size:13px;text-align:center;">이 메일이 보이면 설정이 올바릅니다.</p>
    </div>
    """
    msg.attach(MIMEText(html, 'html'))

    try:
        print('SMTP 연결 중...')
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        print('로그인 중...')
        server.login(username, password)
        print('발송 중...')
        server.sendmail(username, recipient, msg.as_string())
        server.quit()
        print('발송 성공!')
    except Exception as e:
        print(f'발송 실패: {e}')
        sys.exit(1)


if __name__ == '__main__':
    test_smtp()
