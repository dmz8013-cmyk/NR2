"""
cardnews_daily.py — 누렁이 카드뉴스 일일 파이프라인 (하루 1회, 아침)

전날 저녁 브리핑 + 당일 아침 브리핑을 합쳐 하루치 카드뉴스 8장을 생성한다.
  1장   : 표지 (누렁이 마스코트)
  2~7장 : 핵심 이슈 6개 — 뉴스 '장면' 일러스트(사람/사물, 누렁이 없음) 60% + 제목 + 설명 2~3줄
  8장   : 엔딩 (누렁이 마스코트)

흐름:
  브리핑 텍스트(저녁+아침) → Claude 로 상위 6개 이슈 선별 + 설명문 + 영어 장면 프롬프트 생성
  → Replicate flux-1.1-pro 로 장면 일러스트 6장 생성
  → HTML/CSS(v3 템플릿) + Playwright 렌더 → output/cardnews/날짜/
  → 텔레그램 관리자 채팅으로 전송

호출:
  - ai_briefing.send_briefing() 아침 실행 시 run_daily_cardnews_safe()
  - nr2_web_bot 의 /cardnews 수동 트리거

이미지 생성이 하루 1회(6장)로 묶여 있어 비용이 예측 가능하다.
"""

import os
import json
import logging
from datetime import datetime, timedelta

try:
    import anthropic
except ImportError:
    anthropic = None

from cardnews import (
    _extract_json, send_cards_to_telegram, render_cards, _HERE, KST,
)
from cardnews_v3 import build_html, _hero_for

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cardnews_daily")

SELECT_MODEL = "claude-sonnet-4-6"
NUM_ISSUES = 10          # 콘텐츠 카드 수 (표지+엔딩 포함 총 12장)

# 티어 → 카드 표시 라벨 (배열 순서이기도 함: 무거움 → 가벼움)
TIER_LABELS = {
    "headline": "오늘의 1면",
    "core": "핵심",
    "life": "생활",
    "trend": "트렌드",
    "talk": "오늘의 화제",
}
TIER_ORDER = ["headline", "core", "life", "trend", "talk"]
TIER_QUOTA = {"headline": 1, "core": 3, "life": 3, "trend": 2, "talk": 1}


# ══════════════════════════════════════════════════
#  1. Claude — 점수화 + 티어 배열 + 설명문 + 장면 프롬프트
# ══════════════════════════════════════════════════
PROMPT = """당신은 '누렁이 정보공유방' 카드뉴스 편집장입니다.
아래는 오늘 하루치 뉴스 브리핑(어제 저녁 + 오늘 아침)입니다.
카드뉴스 {n}장에 실을 이슈를 2단계로 선별·배열하세요.

[1단계 — 점수화]
브리핑에 등장하는 모든 이슈를 100점 만점으로 평가하세요:
- 생활 영향 (30점): 독자의 돈·건강·일상에 직접 닿는가 (물가·금리·부동산·의료·재해·제도 변화)
- 파급력 (25점): 한국 사회·경제·외교에 구조적 영향을 주는가
- 시의성 (20점): 오늘 새로 발생/전개됐는가, 오늘 알아야 가치가 있는가
- 화제성 (15점): 오늘 사람들의 대화 소재가 될 만한가
- 지속성 (10점): 앞으로 계속 커질 이슈의 시작점/변곡점인가

[2단계 — 티어 배열 (정확히 {n}개, 이 순서대로)]
- "headline" 1개: 종합 최고점. 오늘 하루를 한 장으로 요약하는 이슈
- "core" 3개: 정치·국제·경제의 굵직한 이슈 (티어 내 점수순)
- "life" 3개: 지갑·건강·일상 밀착 이슈 (생활 영향 점수가 높은 것 우선)
- "trend" 2개: AI·테크·문화의 흐름을 보여주는 이슈
- "talk" 1개: 스포츠·연예 등 가볍고 화제성 높은 이슈 (마지막 카드, 스몰토크용)

[배열 규칙]
- issues 배열 순서 = 카드 순서. 위 티어 순서(headline→core→life→trend→talk)를 반드시 지킬 것.
- 같은 분야(cat)는 전체에서 최대 3개까지만.
- 어제 저녁·오늘 아침 브리핑에 같은 사건이 겹치면 하나로 병합하고 최신 내용 기준으로 작성.
- 특정 티어에 맞는 이슈가 정말 없으면 인접 티어 성격의 이슈로 채우되 순서는 유지.

[각 이슈에 필요한 것]
1. cat: 카테고리. "경제" / "정치" / "사회국제" / "생활문화" / "AI" 중 하나
2. tier: "headline" / "core" / "life" / "trend" / "talk" 중 하나
3. score: 1단계에서 매긴 0~100 정수
4. title: 카드 제목 한 줄. 25자 이내. 구어체로 흥미롭게. 이모지 1개까지 허용
5. desc: 설명 2~3문장. "~했어요/~있어요/~한답니다" 체의 친근한 존댓말.
   브리핑에 있는 사실과 수치만 사용. 없는 내용 지어내기 절대 금지.
   각 문장은 완결형으로 끝낼 것. 전체 100~140자.
6. scene_ko: 이 뉴스를 대표하는 일러스트 장면을 한국어로 한 줄 묘사(검수용)
7. image_prompt: 위 장면을 그릴 영어 프롬프트.

[image_prompt 작성 규칙 — 매우 중요]
- 뉴스 내용을 상징하는 '한 장면'을 사람·사물의 행동으로 묘사할 것.
  예) "관리직 거부하는 Z세대" → 사장이 돈다발을 내미는데 젊은 직원이 손사래 치며 나가는 장면
  예) "폭염에 광어 폐사" → 어민이 펄펄 끓는 양식장에 얼음을 붓는 장면
- 실존 인물·기업 로고·상표를 그리지 말 것. 익명의 일반적 인물과 사물로 은유할 것.
- 강아지·동물 마스코트를 넣지 말 것. (표지/엔딩에만 쓰므로 콘텐츠 장면에는 금지)
- 글자·문자를 넣지 말 것. 간판·전광판·서류가 등장하면 반드시 blank(빈 면)로 지정할 것.
- [동작 명확화] 거절·반발·갈등·기피를 다루는 뉴스는 인물의 동작을 모호하지 않게 쓸 것.
  거절이면 "firmly pushing away with both palms, turning her back, walking away" 처럼
  거부 동작을 구체적으로. 반발이면 "arms crossed in protest, shouting with fist raised" 등.
  손을 내밀거나 물건을 만지는 동작은 '받는 것'처럼 보이므로 거절 장면에 쓰지 말 것.
- 영어로, 쉼표로 이어진 시각적 묘사 한 문장. 30단어 이내.

결과물은 오직 아래 JSON 으로만 반환하세요. 설명·마크다운 금지:
{{
  "issues": [
    {{"cat":"경제","tier":"headline","score":87,"title":"제목","desc":"설명 2~3문장","scene_ko":"장면 묘사","image_prompt":"english scene"}}
  ]
}}
issues 배열은 정확히 {n}개여야 합니다.

[오늘 하루치 브리핑]
{briefing}
"""

VALID_CATS = {"경제", "정치", "사회국제", "생활문화", "AI"}


def select_issues(briefing_text: str, n: int = NUM_ISSUES) -> list[dict]:
    """브리핑 → 카드용 이슈 n개(제목·설명·장면 프롬프트 포함)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if anthropic is None:
        raise ImportError("anthropic 패키지가 설치되지 않았습니다.")

    # 10개 이슈 × (점수+설명+장면프롬프트)는 출력이 커서 넉넉한 타임아웃/토큰 필요
    client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=2)
    resp = client.messages.create(
        model=SELECT_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": PROMPT.format(n=n, briefing=briefing_text)}],
    )
    data = _extract_json(resp.content[0].text)

    issues = []
    for it in (data.get("issues") or [])[:n]:
        cat = (it.get("cat") or "기타").strip()
        if cat not in VALID_CATS:
            cat = "기타"
        tier = (it.get("tier") or "").strip()
        if tier not in TIER_LABELS:
            tier = "core"
        try:
            score = max(0, min(100, int(it.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        issues.append({
            "cat": cat,
            "tier": tier,
            "score": score,
            "title": (it.get("title") or "").strip(),
            "desc": (it.get("desc") or "").strip(),
            "scene_ko": (it.get("scene_ko") or "").strip(),
            "image_prompt": (it.get("image_prompt") or "").strip(),
        })
    if not issues:
        raise ValueError("선별된 이슈가 없습니다.")

    # 안전망: Claude가 배열 순서를 어겨도 티어 순(무거움→가벼움) + 티어 내 점수순으로 재정렬
    issues.sort(key=lambda x: (TIER_ORDER.index(x["tier"]), -x["score"]))

    dist = {}
    for i in issues:
        dist[i["tier"]] = dist.get(i["tier"], 0) + 1
    logger.info(f"[카드뉴스] 이슈 {len(issues)}개 선별 완료 — 티어 분포: {dist}")
    return issues


# ══════════════════════════════════════════════════
#  2. 브리핑 텍스트 수집 (저녁 + 아침)
# ══════════════════════════════════════════════════
def collect_today_briefings(morning_briefing: str | None = None) -> str:
    """전날 저녁 + 당일 아침 브리핑 텍스트를 합쳐 반환.

    morning_briefing 이 주어지면(발송 직후 호출) 그것을 아침분으로 쓰고,
    저녁분은 DB에서 조회한다. 둘 다 없으면 DB에서 최근 것을 가져온다.
    """
    parts: list[str] = []
    try:
        from app import create_app
        from app.models.briefing import Briefing
        _app = create_app()
        with _app.app_context():
            since = datetime.now(KST) - timedelta(hours=20)
            evening = Briefing.query.filter(
                Briefing.briefing_type == 'ai_evening',
                Briefing.created_at >= since.replace(tzinfo=None),
            ).order_by(Briefing.created_at.desc()).first()
            if evening:
                parts.append("[어제 저녁 브리핑]\n" + evening.content)

            if morning_briefing:
                parts.append("[오늘 아침 브리핑]\n" + morning_briefing)
            else:
                morning = Briefing.query.filter(
                    Briefing.briefing_type == 'ai_morning',
                ).order_by(Briefing.created_at.desc()).first()
                if morning:
                    parts.append("[오늘 아침 브리핑]\n" + morning.content)
    except Exception as e:
        logger.warning(f"[카드뉴스] DB 브리핑 조회 실패({e}) — 전달받은 텍스트만 사용")
        if morning_briefing and not parts:
            parts.append(morning_briefing)

    if not parts and morning_briefing:
        parts.append(morning_briefing)
    return "\n\n".join(parts)


# ══════════════════════════════════════════════════
#  3. 메인 파이프라인
# ══════════════════════════════════════════════════
def _notify_admin(text: str) -> None:
    """관리자 개인 DM 알림 (실패해도 파이프라인에 영향 없음)."""
    try:
        from app.utils.telegram_notify import send_to_admin
        send_to_admin(text)
    except Exception as e:
        logger.warning(f"[카드뉴스] 관리자 알림 전송 실패: {e}")


def generate_daily_cardnews(briefing_text: str,
                            chat_id: str | None = None) -> tuple[list[str], bool]:
    """브리핑 텍스트 → 8장 생성 → 관리자 텔레그램 전송.

    반환: (PNG 경로 목록, 전송 성공 여부).
    2026-08-02 06:04 사고 교훈: 전송 실패가 반환값으로만 알려지므로
    호출부는 반드시 sent를 확인해야 한다(여기서 관리자 알림까지 처리).
    """
    issues = select_issues(briefing_text)
    # 카드 뱃지에 표시할 티어 라벨 주입 (v3 템플릿은 tier_label만 참조)
    for iss in issues:
        iss["tier_label"] = TIER_LABELS.get(iss.get("tier", ""), "")

    # 장면 일러스트 생성 (실패한 장은 플레이스홀더로 대체되어 렌더는 계속)
    # 요청 간격 12초: 무결제 계정 분당 6건 제한 대응 (결제 등록 후에도 무해)
    import time
    heros = []
    for i, iss in enumerate(issues, 1):
        logger.info(f"[카드뉴스] 일러스트 {i}/{len(issues)} 생성 중… {iss['scene_ko'][:30]}")
        if i > 1:
            time.sleep(12)
        heros.append(_hero_for(iss))

    now = datetime.now(KST)
    html = build_html(issues, heros, now.strftime("%Y.%m.%d"))

    out_dir = os.path.join(_HERE, "output", "cardnews", now.strftime("%Y-%m-%d"))
    paths = render_cards(html, out_dir)

    target = chat_id or os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
    caption = f"🗞️ 누렁이 카드뉴스 · {now.strftime('%Y년 %m월 %d일')}"

    # 부분 실패(일러스트 생성 실패 → 플레이스홀더 카드) 감지 시 관리자에게 별도 알림
    failed = sum(1 for h in heros if not h)
    if failed:
        caption += f" (⚠️ 일러스트 {failed}장 생성 실패)"
        _notify_admin(
            f"⚠️ <b>카드뉴스 부분 실패</b>\n\n"
            f"일러스트 {failed}/{len(heros)}장이 생성되지 않아 "
            f"플레이스홀더로 대체됐습니다.\n"
            f"/cardnews 로 재생성할 수 있습니다."
        )

    sent = send_cards_to_telegram(paths, target, caption=caption)
    if not sent:
        logger.error("[카드뉴스] 텔레그램 전송 최종 실패 — 관리자 알림 발송")
        _notify_admin(
            "❌ <b>카드뉴스 전송 실패</b>\n\n"
            f"8장 생성은 완료됐으나 텔레그램 업로드가 실패했습니다.\n"
            "/cardnews 로 재시도할 수 있습니다."
        )
    return paths, sent


def run_daily_cardnews_safe(morning_briefing: str | None = None) -> None:
    """브리핑 발송과 완전히 분리된 안전 래퍼. 어떤 실패도 밖으로 던지지 않는다.

    완전 실패 시 관리자 DM으로 에러 알림을 보낸다(알림 실패도 무시).
    """
    try:
        text = collect_today_briefings(morning_briefing)
        if not text.strip():
            logger.warning("[카드뉴스] 사용할 브리핑 텍스트가 없음 — 생략")
            _notify_admin("⚠️ <b>카드뉴스 생성 생략</b>\n\n사용할 브리핑 텍스트를 찾지 못했습니다.")
            return
        paths, sent = generate_daily_cardnews(text)
        if sent:
            logger.info(f"[카드뉴스] 완료 ✅ ({len(paths)}장 생성·전송)")
        else:
            logger.error(f"[카드뉴스] 생성 {len(paths)}장 완료, 전송 실패 ❌ (관리자 알림 발송됨)")
    except Exception as e:
        logger.error(f"[카드뉴스] 생성 실패(브리핑 발송에는 영향 없음): {e}", exc_info=True)
        _notify_admin(
            f"❌ <b>카드뉴스 자동 생성 실패</b>\n\n"
            f"오류: {str(e)[:300]}\n\n"
            f"브리핑 발송은 정상입니다. /cardnews 로 수동 재시도할 수 있습니다."
        )


if __name__ == "__main__":
    run_daily_cardnews_safe()
