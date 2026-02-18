#!/usr/bin/env python3
"""Flask 앱 테스트 스크립트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Post

# 앱 생성
app = create_app('development')

with app.app_context():
    # 1. 테스트 유저 생성
    print("=" * 50)
    print("1. 테스트 유저 생성 중...")

    # 기존 테스트 유저 삭제
    existing_user = User.query.filter_by(email='admin@nr2.com').first()
    if existing_user:
        db.session.delete(existing_user)
        db.session.commit()
        print("   기존 테스트 유저 삭제 완료")

    # 관리자 계정 생성
    admin = User(
        email='admin@nr2.com',
        nickname='관리자',
        is_admin=True
    )
    admin.set_password('admin1234')
    db.session.add(admin)

    # 일반 유저 생성
    user1 = User.query.filter_by(email='user1@nr2.com').first()
    if not user1:
        user1 = User(
            email='user1@nr2.com',
            nickname='일반유저1'
        )
        user1.set_password('user1234')
        db.session.add(user1)

    db.session.commit()
    print(f"   ✓ 관리자 계정 생성: {admin.email} / {admin.nickname}")
    print(f"   ✓ 일반 유저 생성: {user1.email} / {user1.nickname}")

    # 2. 테스트 게시글 생성
    print("\n2. 테스트 게시글 생성 중...")

    boards = ['free', 'left', 'right', 'fakenews']
    board_names = {
        'free': '자유게시판',
        'left': 'LEFT게시판',
        'right': 'RIGHT게시판',
        'fakenews': '가짜뉴스게시판'
    }

    for board in boards:
        # 기존 게시글 확인
        existing = Post.query.filter_by(board_type=board).first()
        if not existing:
            post = Post(
                title=f'{board_names[board]} 테스트 게시글',
                content=f'이것은 {board_names[board]}의 테스트 게시글입니다.\n\n자유롭게 의견을 나눠주세요!',
                board_type=board,
                user_id=admin.id
            )
            db.session.add(post)
            print(f"   ✓ {board_names[board]} 게시글 생성")

    db.session.commit()

    # 3. 통계 출력
    print("\n" + "=" * 50)
    print("데이터베이스 통계:")
    print(f"  - 총 사용자 수: {User.query.count()}명")
    print(f"  - 총 게시글 수: {Post.query.count()}개")
    print(f"    ∙ 자유게시판: {Post.query.filter_by(board_type='free').count()}개")
    print(f"    ∙ LEFT게시판: {Post.query.filter_by(board_type='left').count()}개")
    print(f"    ∙ RIGHT게시판: {Post.query.filter_by(board_type='right').count()}개")
    print(f"    ∙ 가짜뉴스게시판: {Post.query.filter_by(board_type='fakenews').count()}개")

    print("\n" + "=" * 50)
    print("테스트 계정 정보:")
    print(f"  관리자: admin@nr2.com / admin1234")
    print(f"  일반유저: user1@nr2.com / user1234")
    print("=" * 50)
    print("\n✅ 테스트 데이터 생성 완료!")
    print(f"\n🌐 서버 접속: http://localhost:5001")
