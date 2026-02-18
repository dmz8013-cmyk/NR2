#!/usr/bin/env python3
"""속보 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User, BreakingNews
from datetime import datetime, timedelta

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("속보 기능 테스트")
    print("=" * 50)

    # 관리자 가져오기
    admin = User.query.filter_by(email='admin@nr2.com').first()

    if not admin:
        print("✗ 관리자 계정이 없습니다.")
        sys.exit(1)

    # 기존 속보 삭제
    BreakingNews.query.delete()
    db.session.commit()

    print("\n1. 테스트 속보 생성 중...")

    # 속보 1: 긴급
    news1 = BreakingNews(
        title='[긴급] 주요 경제 지표 급등, 시장 흔들',
        content='오늘 발표된 경제 지표가 예상을 크게 웃돌며 금융시장에 큰 영향을 미치고 있습니다. 전문가들은 향후 통화정책 변화 가능성에 주목하고 있습니다.\n\n증시는 이번 발표 직후 급등세를 보이고 있으며, 투자자들의 관심이 집중되고 있습니다.',
        source='연합뉴스',
        priority=5,
        user_id=admin.id
    )
    db.session.add(news1)
    print("   ✓ 속보 1: 긴급 경제 뉴스")

    # 속보 2: 중요
    news2 = BreakingNews(
        title='새로운 기술 정책 발표, IT 업계 변화 예고',
        content='정부가 오늘 새로운 기술 정책을 발표했습니다. 이번 정책은 AI, 빅데이터, 클라우드 분야에 대한 대대적인 지원을 포함하고 있습니다.\n\n업계 관계자들은 이번 정책이 국내 IT 산업 발전에 큰 도움이 될 것으로 전망하고 있습니다.',
        source='KBS 뉴스',
        priority=3,
        user_id=admin.id
    )
    db.session.add(news2)
    print("   ✓ 속보 2: 기술 정책 발표")

    # 속보 3: 일반
    news3 = BreakingNews(
        title='국제 스포츠 대회 개최 확정',
        content='2027년 국제 스포츠 대회가 우리나라에서 개최될 예정입니다. IOC는 오늘 공식 발표를 통해 한국을 개최지로 선정했다고 밝혔습니다.\n\n이번 대회는 경제적 효과와 함께 국가 이미지 제고에도 크게 기여할 것으로 예상됩니다.',
        source='자체취재',
        priority=0,
        user_id=admin.id
    )
    db.session.add(news3)
    print("   ✓ 속보 3: 스포츠 뉴스")

    # 속보 4: 중요
    news4 = BreakingNews(
        title='환경 보호 새 법안 통과',
        content='국회에서 새로운 환경 보호 법안이 통과되었습니다. 이번 법안은 탄소 배출 감축과 재생에너지 확대를 주요 내용으로 하고 있습니다.\n\n환경단체들은 이번 법안을 환영하며, 실질적인 이행을 촉구하고 있습니다.',
        source='MBC 뉴스',
        priority=3,
        user_id=admin.id
    )
    db.session.add(news4)
    print("   ✓ 속보 4: 환경 법안")

    # 속보 5: 긴급
    news5 = BreakingNews(
        title='[속보] 대형 교통 사고 발생, 교통 통제 중',
        content='오늘 오전 주요 고속도로에서 대형 교통사고가 발생했습니다. 현재 해당 구간이 전면 통제되고 있으며, 우회도로 이용이 권장되고 있습니다.\n\n경찰과 소방당국이 현장에 출동해 구조 작업을 진행 중입니다.',
        source='연합뉴스',
        priority=5,
        user_id=admin.id
    )
    db.session.add(news5)
    print("   ✓ 속보 5: 교통사고 속보")

    db.session.commit()

    # 통계 출력
    print("\n" + "=" * 50)
    print("속보 통계:")
    print(f"  - 총 속보 수: {BreakingNews.query.count()}개")
    print(f"  - 긴급 속보: {BreakingNews.query.filter(BreakingNews.priority >= 5).count()}개")
    print(f"  - 중요 속보: {BreakingNews.query.filter(BreakingNews.priority >= 3, BreakingNews.priority < 5).count()}개")
    print(f"  - 일반 속보: {BreakingNews.query.filter(BreakingNews.priority < 3).count()}개")

    print("\n속보 목록:")
    for news in BreakingNews.query.order_by(BreakingNews.priority.desc(), BreakingNews.created_at.desc()).all():
        priority_label = "긴급" if news.priority >= 5 else "중요" if news.priority >= 3 else "일반"
        print(f"\n  [{priority_label}] {news.title}")
        print(f"    - 출처: {news.source}")
        print(f"    - 우선순위: {news.priority}")
        print(f"    - 내용: {news.content[:50]}...")

    print("\n" + "=" * 50)
    print("✅ 속보 기능 테스트 완료!")
    print(f"\n속보 페이지: http://localhost:5001/news/breaking")
    print("\n기능:")
    print("  - 우선순위별 정렬 (긴급 > 중요 > 일반)")
    print("  - 출처 표시")
    print("  - 관리자 전용 작성/수정/삭제")
    print("  - 활성화/비활성화")
