"""AESA 기사 재채점 스크립트.

2026-04-10 17:00 UTC (= 2026-04-11 02:00 KST) 경 Anthropic API 크레딧 고갈로
score=0 / status='queued_for_summary'로 잘못 저장된 기사들을 다시 Claude에
채점시켜 DB를 복구한다.

RSS entry의 원문 summary는 DB에 저장되지 않으므로, 제목과 출처만으로 재채점한다.

사용법:
    python scripts/rescore_aesa_articles.py --dry-run  # 대상만 확인
    python scripts/rescore_aesa_articles.py            # 실제 재채점
    python scripts/rescore_aesa_articles.py --limit 20 # 20건만 시험 실행
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import anthropic

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models.aesa_article import AesaArticle
from aesa_monitoring_bot import PROMPT_TEMPLATE

KST = timezone(timedelta(hours=9))
CUTOFF_UTC = datetime(2026, 4, 10, 17, 0, 0, tzinfo=timezone.utc)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def rescore_one(client, article):
    prompt = PROMPT_TEMPLATE.format(
        title=article.title,
        summary="",
        source=article.source,
    )
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        system="당신은 최고 수준의 국제정치, 기술 트렌드, 글로벌 금융 분석가입니다.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    if "{" not in text or "}" not in text:
        raise ValueError(f"Claude 응답에서 JSON을 찾지 못함: {text[:200]}")
    start, end = text.find("{"), text.rfind("}") + 1
    result = json.loads(text[start:end])
    return (
        min(int(result.get("score", 0)), 10),
        result.get("korean_summary", ""),
        result.get("lenses", []),
        bool(result.get("korea_investment_link", False)),
        result.get("korea_insight"),
    )


def decide_status(score):
    """백필용 status 결정.
    9점 이상도 즉시 urgent로 쏘지 않고 queued_batch에 넣어, 일반 15분 배치가
    상위 5건씩 차차 소화하게 한다 (뒤늦은 대량 긴급 알림 폭탄 방지).
    """
    if score >= 7:
        return 'queued_batch'
    return 'queued_for_summary'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='대상만 표시, 변경 없음')
    parser.add_argument('--limit', type=int, default=None, help='최대 처리 건수')
    parser.add_argument('--sleep', type=float, default=0.3, help='Claude 호출 사이 대기초')
    parser.add_argument('--commit-every', type=int, default=20, help='N건마다 DB commit')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        q = AesaArticle.query.filter(
            AesaArticle.status == 'queued_for_summary',
            AesaArticle.score == 0,
            AesaArticle.created_at > CUTOFF_UTC,
        ).order_by(AesaArticle.created_at.asc())
        if args.limit:
            q = q.limit(args.limit)
        targets = q.all()

        logger.info(f"재채점 대상: {len(targets)}건")
        if not targets:
            return

        if args.dry_run:
            for a in targets[:10]:
                logger.info(f"  [dry] id={a.id} {a.source} | {a.title[:60]}")
            if len(targets) > 10:
                logger.info(f"  ... 외 {len(targets) - 10}건")
            logger.info("Dry run — 변경 사항 없음")
            return

        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            logger.error("ANTHROPIC_API_KEY 환경변수 없음")
            sys.exit(1)

        client = anthropic.Anthropic(api_key=api_key, timeout=25.0)
        dist = {'9+': 0, '7-8': 0, '1-6': 0, 'failed': 0}

        for i, a in enumerate(targets, 1):
            logger.info(f"[{i}/{len(targets)}] {a.source} | {a.title[:60]}")
            try:
                score, summary, lenses, korea_link, korea_insight = rescore_one(client, a)
            except anthropic.BadRequestError as e:
                msg = str(e).lower()
                if 'credit balance' in msg or 'too low' in msg:
                    logger.error("Anthropic 크레딧 재고갈 감지 — 중단")
                    db.session.commit()
                    sys.exit(2)
                logger.error(f"  BadRequest: {e}")
                dist['failed'] += 1
                continue
            except Exception as e:
                logger.error(f"  실패: {e}")
                dist['failed'] += 1
                continue

            a.score = score
            a.summary = summary
            a.lenses = ','.join(lenses) if lenses else ''
            a.korea_investment_link = korea_link
            a.korea_insight = korea_insight
            a.status = decide_status(score)

            if score >= 9:
                dist['9+'] += 1
            elif score >= 7:
                dist['7-8'] += 1
            else:
                dist['1-6'] += 1

            logger.info(f"  -> score={score} status={a.status}")

            if i % args.commit_every == 0:
                db.session.commit()
                logger.info(f"  [commit] {i}/{len(targets)}")

            time.sleep(args.sleep)

        db.session.commit()
        logger.info("=" * 50)
        logger.info(f"완료. 분포: {dist}")
        logger.info(f"queued_batch 로 이동된 7점+ 기사는 다음 15분 배치 주기부터 상위 5건씩 발송됨")


if __name__ == '__main__':
    main()
