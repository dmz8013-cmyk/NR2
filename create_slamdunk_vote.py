#!/usr/bin/env python3
"""슬램덩크 투표 생성"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Vote, VoteOption
from datetime import datetime, timedelta

app = create_app('development')

with app.app_context():
    print("=" * 60)
    print("🏀 슬램덩크 투표 생성")
    print("=" * 60)

    # 관리자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()

    if not admin:
        print("✗ 관리자 계정이 없습니다.")
        sys.exit(1)

    # 기존 슬램덩크 투표 확인 및 삭제
    existing_vote = Vote.query.filter(Vote.title.like('%슬램덩크%')).first()
    if existing_vote:
        print("\n기존 슬램덩크 투표 삭제 중...")
        db.session.delete(existing_vote)
        db.session.commit()
        print("✓ 기존 투표 삭제 완료")

    print("\n투표 생성 중...")

    # 슬램덩크 투표 생성
    vote = Vote(
        title='🏀 슬램덩크 북산고등학교 최고의 선수는?',
        description='만화 슬램덩크의 북산고 농구부에서 가장 뛰어난 선수를 선택해주세요!\n\n각 선수들은 독특한 재능과 매력을 가지고 있습니다. 여러분이 생각하는 최고의 선수에게 투표해주세요!',
        is_multiple=False,  # 단일 선택
        end_date=datetime.utcnow() + timedelta(days=30),  # 30일간 진행
        user_id=admin.id
    )
    db.session.add(vote)
    db.session.flush()  # ID 생성

    print(f"✓ 투표 생성 완료: {vote.title}")

    # 선수 옵션 추가
    players = [
        '🔥 강백호 (파워 포워드)',
        '⭐ 서태웅 (슈팅가드)',
        '💪 채치수 (센터)',
        '😎 정대만 (스몰 포워드)',
        '🎯 송태섭 (포인트가드)',
        '⚡ 권준호 (식스맨)'
    ]

    print("\n선수 옵션 추가 중...")
    for idx, player_name in enumerate(players):
        option = VoteOption(
            vote_id=vote.id,
            text=player_name,
            order=idx
        )
        db.session.add(option)
        print(f"  ✓ {player_name}")

    db.session.commit()

    # 결과 확인
    vote = Vote.query.filter(Vote.title.like('%슬램덩크%')).first()

    print("\n" + "=" * 60)
    print("✅ 슬램덩크 투표 생성 완료!")
    print("=" * 60)

    print(f"\n📋 투표 정보:")
    print(f"  - 제목: {vote.title}")
    print(f"  - 투표 방식: 단일 선택")
    print(f"  - 종료일: {vote.end_date.strftime('%Y년 %m월 %d일')}")
    print(f"  - 선택지: {vote.options.count()}개")

    print(f"\n🏀 선수 목록:")
    for option in vote.options.order_by('order'):
        print(f"  {option.text}")

    print(f"\n🌐 투표 페이지:")
    print(f"  http://localhost:5001/votes/{vote.id}")
    print(f"\n📊 투표 목록:")
    print(f"  http://localhost:5001/votes/")

    print("\n" + "=" * 60)
