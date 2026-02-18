#!/usr/bin/env python3
"""투표 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Vote, VoteOption, VoteResponse
from datetime import datetime, timedelta

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("투표 기능 테스트")
    print("=" * 50)

    # 사용자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()
    user1 = User.query.filter_by(email='user1@nr2.com').first()

    if not admin or not user1:
        print("✗ 테스트 사용자가 없습니다.")
        sys.exit(1)

    # 기존 투표 삭제
    Vote.query.delete()
    db.session.commit()

    print("\n1. 테스트 투표 생성 중...")

    # 투표 1: 단일 선택
    vote1 = Vote(
        title='좋아하는 프로그래밍 언어는?',
        description='개발할 때 가장 선호하는 프로그래밍 언어를 선택해주세요.',
        is_multiple=False,
        user_id=admin.id
    )
    db.session.add(vote1)
    db.session.flush()

    options1 = [
        VoteOption(text='Python', order=0, vote_id=vote1.id),
        VoteOption(text='JavaScript', order=1, vote_id=vote1.id),
        VoteOption(text='Java', order=2, vote_id=vote1.id),
        VoteOption(text='C++', order=3, vote_id=vote1.id),
        VoteOption(text='Go', order=4, vote_id=vote1.id),
    ]
    for opt in options1:
        db.session.add(opt)

    print("   ✓ 투표 1 생성 (단일 선택)")

    # 투표 2: 복수 선택
    vote2 = Vote(
        title='관심있는 기술 스택 (복수 선택)',
        description='현재 관심을 가지고 있거나 배우고 싶은 기술을 모두 선택해주세요.',
        is_multiple=True,
        user_id=user1.id
    )
    db.session.add(vote2)
    db.session.flush()

    options2 = [
        VoteOption(text='프론트엔드 (React, Vue)', order=0, vote_id=vote2.id),
        VoteOption(text='백엔드 (Django, Flask)', order=1, vote_id=vote2.id),
        VoteOption(text='데이터베이스', order=2, vote_id=vote2.id),
        VoteOption(text='DevOps', order=3, vote_id=vote2.id),
        VoteOption(text='AI/ML', order=4, vote_id=vote2.id),
    ]
    for opt in options2:
        db.session.add(opt)

    print("   ✓ 투표 2 생성 (복수 선택)")

    # 투표 3: 종료일 있는 투표
    vote3 = Vote(
        title='다음 커뮤니티 이벤트 주제는?',
        description='다음 달에 진행할 이벤트 주제를 투표로 결정합니다.',
        is_multiple=False,
        end_date=datetime.now() + timedelta(days=7),
        user_id=admin.id
    )
    db.session.add(vote3)
    db.session.flush()

    options3 = [
        VoteOption(text='코딩 챌린지', order=0, vote_id=vote3.id),
        VoteOption(text='기술 세미나', order=1, vote_id=vote3.id),
        VoteOption(text='네트워킹 모임', order=2, vote_id=vote3.id),
        VoteOption(text='해커톤', order=3, vote_id=vote3.id),
    ]
    for opt in options3:
        db.session.add(opt)

    print("   ✓ 투표 3 생성 (종료일 있음)")

    db.session.commit()

    # 테스트 투표 참여
    print("\n2. 테스트 투표 참여 중...")

    # 관리자가 투표1에 참여
    response1 = VoteResponse(user_id=admin.id, vote_id=vote1.id, option_id=options1[0].id)
    db.session.add(response1)

    # 일반유저가 투표1에 참여
    response2 = VoteResponse(user_id=user1.id, vote_id=vote1.id, option_id=options1[1].id)
    db.session.add(response2)

    # 관리자가 투표2에 참여 (복수 선택)
    response3 = VoteResponse(user_id=admin.id, vote_id=vote2.id, option_id=options2[0].id)
    response4 = VoteResponse(user_id=admin.id, vote_id=vote2.id, option_id=options2[4].id)
    db.session.add(response3)
    db.session.add(response4)

    db.session.commit()
    print("   ✓ 투표 참여 완료")

    # 통계 출력
    print("\n" + "=" * 50)
    print("투표 통계:")
    print(f"  - 총 투표 수: {Vote.query.count()}개")
    print(f"  - 진행중: {Vote.query.filter(Vote.end_date == None).count()}개")
    print(f"  - 총 참여 수: {VoteResponse.query.count()}회")

    print("\n투표 목록:")
    for vote in Vote.query.all():
        print(f"\n  • {vote.title}")
        print(f"    - 참여: {vote.total_votes}명")
        print(f"    - 복수선택: {'예' if vote.is_multiple else '아니오'}")
        if vote.end_date:
            print(f"    - 종료일: {vote.end_date.strftime('%Y-%m-%d')}")
        for option in vote.options.order_by('order'):
            print(f"      [{option.votes_count}표] {option.text} ({option.percentage:.1f}%)")

    print("\n" + "=" * 50)
    print("✅ 투표 테스트 완료!")
    print(f"\n투표 목록: http://localhost:5001/votes")
