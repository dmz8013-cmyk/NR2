#!/usr/bin/env python3
"""캘린더 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, Event
from datetime import datetime, timedelta

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("캘린더 기능 테스트")
    print("=" * 50)

    # 사용자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()
    user1 = User.query.filter_by(email='user1@nr2.com').first()

    if not admin or not user1:
        print("✗ 테스트 사용자가 없습니다.")
        sys.exit(1)

    # 기존 일정 삭제
    Event.query.filter_by(user_id=admin.id).delete()
    db.session.commit()

    print("\n1. 테스트 일정 생성 중...")

    today = datetime.now()

    # 일정 1: 오늘 미팅
    event1 = Event(
        title='프로젝트 회의',
        description='Q1 프로젝트 진행 상황 점검 회의',
        start_date=today.replace(hour=14, minute=0, second=0, microsecond=0),
        end_date=today.replace(hour=15, minute=30, second=0, microsecond=0),
        all_day=False,
        color='#3B82F6',
        user_id=admin.id
    )
    db.session.add(event1)
    print("   ✓ 일정 1: 프로젝트 회의 (오늘 14:00)")

    # 일정 2: 내일 종일 이벤트
    event2 = Event(
        title='워크샵',
        description='팀 빌딩 워크샵',
        start_date=(today + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
        end_date=None,
        all_day=True,
        color='#10B981',
        user_id=admin.id
    )
    db.session.add(event2)
    print("   ✓ 일정 2: 워크샵 (내일, 종일)")

    # 일정 3: 다음주 생일
    event3 = Event(
        title='동료 생일',
        description='케이크 준비하기',
        start_date=(today + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0),
        end_date=None,
        all_day=True,
        color='#EC4899',
        user_id=admin.id
    )
    db.session.add(event3)
    print("   ✓ 일정 3: 동료 생일 (다음주)")

    # 일정 4: 정기 회의
    event4 = Event(
        title='주간 스탠드업',
        description='매주 월요일 아침 회의',
        start_date=(today + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0),
        end_date=(today + timedelta(days=3)).replace(hour=9, minute=30, second=0, microsecond=0),
        all_day=False,
        color='#8B5CF6',
        user_id=admin.id
    )
    db.session.add(event4)
    print("   ✓ 일정 4: 주간 스탠드업")

    # 일정 5: 마감일
    event5 = Event(
        title='프로젝트 마감',
        description='프로젝트 최종 제출',
        start_date=(today + timedelta(days=14)).replace(hour=23, minute=59, second=0, microsecond=0),
        end_date=None,
        all_day=False,
        color='#EF4444',
        user_id=admin.id
    )
    db.session.add(event5)
    print("   ✓ 일정 5: 프로젝트 마감 (2주 후)")

    db.session.commit()

    # 통계 출력
    print("\n" + "=" * 50)
    print("캘린더 통계:")
    print(f"  - 총 일정 수: {Event.query.filter_by(user_id=admin.id).count()}개")
    print(f"  - 종일 일정: {Event.query.filter_by(user_id=admin.id, all_day=True).count()}개")
    print(f"  - 시간 지정 일정: {Event.query.filter_by(user_id=admin.id, all_day=False).count()}개")

    print("\n일정 목록:")
    for event in Event.query.filter_by(user_id=admin.id).order_by(Event.start_date):
        print(f"\n  • {event.title}")
        if event.all_day:
            print(f"    - 날짜: {event.start_date.strftime('%Y-%m-%d')} (종일)")
        else:
            print(f"    - 시작: {event.start_date.strftime('%Y-%m-%d %H:%M')}")
            if event.end_date:
                print(f"    - 종료: {event.end_date.strftime('%Y-%m-%d %H:%M')}")
        if event.description:
            print(f"    - 설명: {event.description}")
        print(f"    - 색상: {event.color}")

    print("\n" + "=" * 50)
    print("✅ 캘린더 테스트 완료!")
    print(f"\n캘린더 페이지: http://localhost:5001/calendar/")
    print("\n기능:")
    print("  - 월/주/일 뷰 전환")
    print("  - 일정 드래그 앤 드롭")
    print("  - 일정 클릭하여 수정/삭제")
    print("  - 날짜 선택하여 새 일정 추가")
