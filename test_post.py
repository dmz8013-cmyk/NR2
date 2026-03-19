"""테스트 게시물 생성 + 텔레그램 알림 발송 확인 스크립트"""
import os
os.environ.setdefault('FLASK_ENV', 'production')

from app import create_app, db
from app.models.post import Post
from app.models.user import User
from app.utils.telegram_notify import notify_new_post

app = create_app()

with app.app_context():
    # 관리자 계정 찾기
    admin = User.query.filter_by(email='dmz8013@gmail.com').first()
    if not admin:
        print("❌ 관리자 계정을 찾을 수 없습니다.")
        exit(1)

    print(f"✅ 관리자: {admin.nickname} (id={admin.id})")

    # 테스트 게시물 생성
    post = Post(
        title='[테스트] 텔레그램 알림 발송 확인용 게시물',
        content='텔레그램 채널 알림이 제대로 발송되는지 확인하는 테스트입니다.',
        board_type='free',
        user_id=admin.id,
    )
    db.session.add(post)
    db.session.commit()
    print(f"✅ 게시물 생성 완료 (id={post.id}, board=free)")

    # 텔레그램 알림 발송
    result = notify_new_post(post)
    if result:
        print("✅ 텔레그램 채널 발송 성공! @gazzzza2025 확인하세요.")
    else:
        print("⚠️  텔레그램 발송 실패 — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수 확인")

    print(f"\n🔗 https://nr2.kr/boards/free/{post.id}")
