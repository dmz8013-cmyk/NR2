"""2026 경제·AI 기술 브리핑 아티클을 누렁이 AESA 게시판에 등록하는 스크립트"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User
from app.models.post import Post

TITLE = '2026 경제·산업 전망 및 글로벌 AI 기술 혁신 브리핑'


def main():
    app = create_app()
    with app.app_context():
        bot = User.query.filter_by(nickname='누렁이봇').first()
        if not bot:
            bot = User.query.filter_by(is_admin=True).first()
        if not bot:
            bot = User.query.get(1)
        if not bot:
            print('ERROR: 사용할 수 있는 계정이 없습니다.')
            return

        print(f'작성자: id={bot.id}, nickname={bot.nickname}')

        existing = Post.query.filter_by(title=TITLE, board_type='aesa').first()
        if existing:
            print(f'이미 존재함: post_id={existing.id}')
            return

        content_path = os.path.join(os.path.dirname(__file__), 'seed_aesa_briefing_content.html')
        with open(content_path, 'r', encoding='utf-8') as f:
            content = f.read()

        post = Post(
            title=TITLE,
            content=content,
            board_type='aesa',
            user_id=bot.id,
        )
        db.session.add(post)
        db.session.commit()
        print(f'게시 완료: post_id={post.id}')
        print(f'URL: https://nr2.kr/boards/aesa/{post.id}')


if __name__ == '__main__':
    main()
