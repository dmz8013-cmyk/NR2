#!/usr/bin/env python3
"""페이지네이션 테스트를 위한 게시글 생성"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Post
from datetime import datetime, timedelta
import random

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("페이지네이션 테스트 데이터 생성")
    print("=" * 50)

    # 사용자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()
    user1 = User.query.filter_by(email='user1@nr2.com').first()

    if not admin or not user1:
        print("✗ 테스트 사용자가 없습니다.")
        sys.exit(1)

    users = [admin, user1]
    boards = ['free', 'left', 'right', 'fakenews']
    board_names = {
        'free': '자유게시판',
        'left': 'LEFT게시판',
        'right': 'RIGHT게시판',
        'fakenews': '가짜뉴스게시판'
    }

    print("\n게시글 생성 중...")

    # 각 게시판에 50개씩 게시글 생성
    total_created = 0
    for board_type in boards:
        existing_count = Post.query.filter_by(board_type=board_type).count()

        # 최소 50개가 되도록 생성
        needed = max(0, 50 - existing_count)

        if needed > 0:
            print(f"\n{board_names[board_type]}:")
            for i in range(needed):
                # 랜덤 사용자 선택
                user = random.choice(users)

                # 시간을 과거로 설정 (최신순 정렬 확인용)
                created_time = datetime.utcnow() - timedelta(
                    days=random.randint(0, 30),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59)
                )

                post = Post(
                    title=f'{board_names[board_type]} 테스트 게시글 #{existing_count + i + 1}',
                    content=f'이것은 페이지네이션 테스트를 위한 게시글입니다.\n\n게시글 번호: {existing_count + i + 1}\n작성자: {user.nickname}\n게시판: {board_names[board_type]}',
                    board_type=board_type,
                    user_id=user.id,
                    views=random.randint(0, 100),
                    created_at=created_time
                )
                db.session.add(post)
                total_created += 1

                # 10개마다 커밋
                if (i + 1) % 10 == 0:
                    db.session.commit()
                    print(f"  {i + 1}개 생성...")

            db.session.commit()
            print(f"  ✓ 총 {needed}개 생성 완료")
        else:
            print(f"\n{board_names[board_type]}: 이미 {existing_count}개 존재 (생략)")

    print("\n" + "=" * 50)
    print("통계:")
    for board_type in boards:
        count = Post.query.filter_by(board_type=board_type).count()
        pages = (count + 19) // 20  # 페이지당 20개
        print(f"  {board_names[board_type]}: {count}개 (약 {pages}페이지)")

    print(f"\n총 생성된 게시글: {total_created}개")
    print("=" * 50)
    print("✅ 테스트 데이터 생성 완료!")
    print("\n게시판 확인:")
    print("  - http://localhost:5001/boards/free")
    print("  - http://localhost:5001/boards/left")
    print("  - http://localhost:5001/boards/right")
    print("  - http://localhost:5001/boards/fakenews")
