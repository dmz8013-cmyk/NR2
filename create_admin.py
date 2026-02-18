"""Railway PostgreSQL 관리자 계정 생성 스크립트

사용법:
    DATABASE_URL=postgresql://... python create_admin.py
    또는 .env에 DATABASE_URL이 설정된 경우:
    python create_admin.py
"""

import os
import sys
import getpass
from dotenv import load_dotenv

load_dotenv()

# DATABASE_URL 확인
database_url = os.environ.get('DATABASE_URL', '')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

if not database_url:
    print('오류: DATABASE_URL 환경변수가 설정되지 않았습니다.')
    print('Railway 대시보드 → Variables에서 DATABASE_URL을 복사해 .env에 추가하세요.')
    sys.exit(1)

os.environ['DATABASE_URL'] = database_url

# Flask 앱 컨텍스트 로드
from app import create_app, db
from app.models import User

app = create_app()

ADMIN_EMAIL    = 'dmz8013@gmail.com'
ADMIN_NICKNAME = '누렁이(SOB)'

with app.app_context():
    # 비밀번호 입력
    while True:
        password = getpass.getpass('비밀번호 입력: ')
        confirm  = getpass.getpass('비밀번호 확인: ')
        if password != confirm:
            print('비밀번호가 일치하지 않습니다. 다시 입력해주세요.')
            continue
        if len(password) < 6:
            print('비밀번호는 최소 6자 이상이어야 합니다.')
            continue
        break

    # 기존 계정 확인
    existing = User.query.filter_by(email=ADMIN_EMAIL).first()

    if existing:
        existing.nickname  = ADMIN_NICKNAME
        existing.is_admin  = True
        existing.set_password(password)
        db.session.commit()
        print(f'기존 계정을 관리자로 업데이트했습니다: {ADMIN_EMAIL}')
    else:
        user = User(email=ADMIN_EMAIL, nickname=ADMIN_NICKNAME, is_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f'관리자 계정 생성 완료: {ADMIN_EMAIL} / {ADMIN_NICKNAME}')
