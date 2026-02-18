#!/usr/bin/env python3
"""댓글 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Post, Comment

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("댓글 기능 테스트")
    print("=" * 50)

    # 테스트용 게시글 찾기
    post = Post.query.first()
    if not post:
        print("✗ 테스트용 게시글이 없습니다.")
        sys.exit(1)

    print(f"\n테스트 게시글: {post.title}")

    # 기존 댓글 삭제
    Comment.query.filter_by(post_id=post.id).delete()
    db.session.commit()

    # 사용자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()
    user1 = User.query.filter_by(email='user1@nr2.com').first()

    # 1. 댓글 작성
    print("\n1. 댓글 작성 중...")
    comment1 = Comment(
        content='첫 번째 댓글입니다!',
        user_id=admin.id,
        post_id=post.id
    )
    db.session.add(comment1)

    comment2 = Comment(
        content='두 번째 댓글입니다.',
        user_id=user1.id,
        post_id=post.id
    )
    db.session.add(comment2)
    db.session.commit()
    print(f"   ✓ 댓글 2개 작성 완료")

    # 2. 대댓글 작성
    print("\n2. 대댓글 작성 중...")
    reply1 = Comment(
        content='첫 번째 댓글에 대한 답글입니다.',
        user_id=user1.id,
        post_id=post.id,
        parent_id=comment1.id
    )
    db.session.add(reply1)

    reply2 = Comment(
        content='또 다른 답글입니다!',
        user_id=admin.id,
        post_id=post.id,
        parent_id=comment1.id
    )
    db.session.add(reply2)
    db.session.commit()
    print(f"   ✓ 대댓글 2개 작성 완료")

    # 3. 통계 출력
    print("\n" + "=" * 50)
    print("댓글 통계:")
    print(f"  - 총 댓글 수: {Comment.query.filter_by(post_id=post.id).count()}개")
    print(f"  - 일반 댓글: {Comment.query.filter_by(post_id=post.id, parent_id=None).count()}개")
    print(f"  - 대댓글: {Comment.query.filter_by(post_id=post.id).filter(Comment.parent_id.isnot(None)).count()}개")

    print("\n댓글 목록:")
    for comment in Comment.query.filter_by(post_id=post.id, parent_id=None).all():
        print(f"  • {comment.author.nickname}: {comment.content[:30]}...")
        for reply in comment.replies.all():
            print(f"    ↳ {reply.author.nickname}: {reply.content[:30]}...")

    print("\n" + "=" * 50)
    print("✅ 테스트 댓글 생성 완료!")
    print(f"\n게시글 확인: http://localhost:5001/boards/{post.board_type}/{post.id}")
