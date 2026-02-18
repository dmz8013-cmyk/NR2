#!/usr/bin/env python3
"""좋아요 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Post, Like

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("좋아요 기능 테스트")
    print("=" * 50)

    # 테스트용 게시글 찾기
    post = Post.query.first()
    if not post:
        print("✗ 테스트용 게시글이 없습니다.")
        sys.exit(1)

    print(f"\n테스트 게시글: {post.title}")

    # 기존 좋아요 삭제
    Like.query.filter_by(post_id=post.id).delete()
    db.session.commit()

    # 사용자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()
    user1 = User.query.filter_by(email='user1@nr2.com').first()

    # 1. 좋아요 추가
    print("\n1. 좋아요 추가 중...")
    like1 = Like(user_id=admin.id, post_id=post.id)
    like2 = Like(user_id=user1.id, post_id=post.id)
    db.session.add(like1)
    db.session.add(like2)
    db.session.commit()
    print(f"   ✓ 좋아요 2개 추가 완료")

    # 2. 좋아요 개수 확인
    print(f"\n2. 좋아요 개수: {post.likes_count}개")

    # 3. 중복 좋아요 방지 테스트
    print("\n3. 중복 좋아요 방지 테스트...")
    try:
        duplicate_like = Like(user_id=admin.id, post_id=post.id)
        db.session.add(duplicate_like)
        db.session.commit()
        print("   ✗ 중복 좋아요가 추가됨 (오류)")
    except Exception as e:
        db.session.rollback()
        print("   ✓ 중복 좋아요 방지 성공")

    # 4. 좋아요 취소
    print("\n4. 좋아요 취소 테스트...")
    like = Like.query.filter_by(user_id=admin.id, post_id=post.id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
        print("   ✓ 좋아요 취소 완료")
        print(f"   현재 좋아요 개수: {post.likes_count}개")

    # 5. 통계 출력
    print("\n" + "=" * 50)
    print("좋아요 통계:")
    print(f"  - 총 좋아요 수: {Like.query.count()}개")
    print(f"  - 이 게시글 좋아요: {post.likes_count}개")
    print("\n좋아요 목록:")
    for like in Like.query.filter_by(post_id=post.id).all():
        print(f"  • {like.user.nickname}")

    print("\n" + "=" * 50)
    print("✅ 좋아요 기능 테스트 완료!")
    print(f"\n게시글 확인: http://localhost:5001/boards/{post.board_type}/{post.id}")
