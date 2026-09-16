"""
cardnews_daily.py — 누렁이 카드뉴스 일일 파이프라인 (하루 1회, 아침)

전날 저녁 브리핑 + 당일 아침 브리핑을 합쳐 하루치 카드뉴스 8장을 생성한다.
  1장   : 표지 (누렁이 마스코트)
  2~7장 : 핵심 이슈 6개 — 뉴스 '장면' 일러스트(사람/사물, 누렁이 없음) 60% + 제목 + 설명 2~3줄
  8장   : 엔딩 (누렁이 마스코트)

흐름:
  브리핑 텍스트(저녁+아침) → Claude 로 상위 6개 이슈 선별 + 설명문 + 영어 장면 프롬프트 생성
  → Replicate flux-1.1-pro 로 장면 일러스트 6장 생성
  → HTML/CSS(v3/v4 템플릿) + Playwright 렌더 → output/cardnews/날짜/
  → 고정값 사전(config/fixed_facts.json) 대조 → 관리자 DM 미리보기(앨범+텍스트)
  → /card_ok 승인 시에만 채널 발행 (자동발행 없음) / /card_no 폐기

입력 원칙: verify_pass·레이아웃 적용이 끝난 브리핑 최종본만 받는다
(send_briefing 발송 직후 전달분 또는 DB 저장분 — 둘 다 최종본). 원문 피드 직결 금지.

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
NUM_ISSUES = 10          # 국내 콘텐츠 카드 수
NUM_WORLD = 3            # 외신 카드 수 (표지+국내10+외신3+엔딩 = 총 15장)

# 티어 → 카드 표시 라벨 (배열 순서이기도 함: 무거움 → 가벼움 → 외신 블록)
TIER_LABELS = {
    "headline": "오늘의 1면",
    "core": "핵심",
    "life": "생활",
    "trend": "트렌드",
    "talk": "오늘의 화제",
    "world": "",            # 외신은 뱃지(🌍 외신 · NN)로 이미 구분 — 티어 칩 생략
}
TIER_ORDER = ["headline", "core", "life", "trend", "talk", "world"]
TIER_QUOTA = {"headline": 1, "core": 3, "life": 3, "trend": 2, "talk": 1, "world": 3}


# ══════════════════════════════════════════════════
#  1. Claude — 점수화 + 티어 배열 + 설명문 + 장면 프롬프트
# ══════════════════════════════════════════════════
PROMPT = """당신은 '누렁이 정보공유방' 카드뉴스 편집장입니다.
아래는 오늘 하루치 뉴스 브리핑(어제 저녁 + 오늘 아침)입니다.
국내 카드 {n}장에 실을 이슈를 2단계로 선별·배열하세요.{world_intro}

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

{world_section}[각 이슈에 필요한 것]
1. cat: 카테고리. 국내 카드는 "경제" / "정치" / "사회국제" / "생활문화" / "AI" 중 하나,
   외신 카드는 반드시 "외신"
2. tier: 국내 카드는 "headline" / "core" / "life" / "trend" / "talk", 외신 카드는 "world"
3. score: 1단계에서 매긴 0~100 정수 (외신은 AESA 점수 × 10)
4. title: 카드 제목. 구어체로 흥미롭게, 최대 임팩트. 이모지 1개까지 허용.
   [길이 엄수] 공백 포함 20자 이내 — 카드에서 최대 2줄로 렌더되므로
   20자를 넘기면 안 됨. 조사·수식어를 줄여서라도 20자 안에 압축할 것.
5. subtitle: 부제 1줄, 공백 포함 22자 이내. 핵심 수치나 인용 한 토막을 담는 명사형
   (예: '기준금리 3.00% 동결', '피해자 1인당 10만 원'). 브리핑에 있는 수치만.
6. bullets: 요점 정확히 3개. 각 25자 이내, 명사형 종결(~확정/~전망/~반발 등, 서술형 '~했어요' 금지).
   브리핑에 있는 사실과 수치만 사용. 없는 내용 지어내기 절대 금지.
7. desc: 설명 2~3문장. "~했어요/~있어요/~한답니다" 체의 친근한 존댓말.
   브리핑에 있는 사실과 수치만 사용. 없는 내용 지어내기 절대 금지.
   각 문장은 완결형으로 끝낼 것. 전체 100~140자.
8. scene_ko: 이 뉴스를 대표하는 일러스트 장면을 한국어로 한 줄 묘사(검수용)
9. image_prompt: 위 장면을 그릴 영어 프롬프트.

[사실 규칙 — 최우선] 아래 사전과 충돌하는 수치·직함·소속은 브리핑 원문에 있어도 쓰지 말 것.
사전과 충돌하는 이슈는 사전 값으로 고쳐 쓰거나, 고칠 수 없으면 그 이슈를 제외할 것.
{facts_block}

[image_prompt 작성 규칙 — 매우 중요]
- 뉴스 내용을 상징하는 '한 장면'을 사람·사물의 행동으로 묘사할 것.
  예) "관리직 거부하는 Z세대" → 사장이 돈다발을 내미는데 젊은 직원이 손사래 치며 나가는 장면
  예) "폭염에 광어 폐사" → 어민이 펄펄 끓는 양식장에 얼음을 붓는 장면
- 실존 인물·기업 로고·상표를 그리지 말 것. 익명의 일반적 인물과 사물로 은유할 것.
- 강아지·동물 마스코트를 넣지 말 것. (표지/엔딩에만 쓰므로 콘텐츠 장면에는 금지)
- 글자·문자를 넣지 말 것. 간판·전광판·서류가 등장하면 반드시 blank(빈 면)로 지정할 것.
- [인물 국적 — 매우 중요] 국내 뉴스 카드의 인물은 반드시 한국인으로 명시할 것:
  "Korean" 을 인물마다 붙이고(예: "Korean office workers", "a Korean homeowner"),
  배경도 한국으로(예: "Korean city street", "Korean apartment complex", "Korean office").
  복장·거리·간판(빈 면)도 한국 일상 디테일로. 이미지 모델은 지시가 없으면 서양인을
  기본으로 그리므로, 국내 카드에서 인물 국적 명시를 절대 빠뜨리지 말 것.
  서양 정치인 연상 인물(특히 금발의 서양 정치인 스타일) 절대 금지.
  예외: 외신 카드는 해당 국가 인물·배경을 그대로 쓸 것(미국 뉴스면 American 등).
- [동작 명확화] 거절·반발·갈등·기피를 다루는 뉴스는 인물의 동작을 모호하지 않게 쓸 것.
  거절이면 "firmly pushing away with both palms, turning her back, walking away" 처럼
  거부 동작을 구체적으로. 반발이면 "arms crossed in protest, shouting with fist raised" 등.
  손을 내밀거나 물건을 만지는 동작은 '받는 것'처럼 보이므로 거절 장면에 쓰지 말 것.
- 영어로, 쉼표로 이어진 시각적 묘사 한 문장. 30단어 이내.

[JSON 안전 규칙] title·desc·scene_ko 등 모든 텍스트 필드 안에서 큰따옴표(")를
절대 쓰지 말 것 — 발언 인용이 필요하면 작은따옴표(')로 대체. (JSON 파싱 오류 방지)

결과물은 오직 아래 JSON 으로만 반환하세요. 설명·마크다운 금지:
{{
  "issues": [
    {{"cat":"경제","tier":"headline","score":87,"title":"제목","subtitle":"부제 1줄","bullets":["요점1","요점2","요점3"],"desc":"설명 2~3문장","scene_ko":"장면 묘사","image_prompt":"english scene"}}
  ]
}}
issues 배열은 정확히 {total}개(국내 {n}개{world_count_note})여야 합니다.

[오늘 하루치 브리핑]
{briefing}
"""

VALID_CATS = {"경제", "정치", "사회국제", "생활문화", "AI", "외신"}
DRAFT_STATE_KEY = "cardnews_draft"      # g2b_state — 미리보기 후 /card_ok 대기 초안


def _facts_block() -> str:
    """고정값 사전(fixed_facts.json) + 브리핑 팩트사전(facts.json) → 프롬프트 주입 블록.

    브리핑은 발행 전 verify_pass 로 검증되지만, 카드 문구는 여기서 Claude 가 다시
    써 내려가므로 같은 사전을 한 번 더 주입해 '재작성 중 오류 재유입'을 막는다.
    실패해도 빈 문자열 — 카드 생성은 계속."""
    parts = []
    try:
        from fixed_facts import fixed_facts_context
        fx = fixed_facts_context()
        if fx:
            parts.append(fx)
    except Exception as e:
        logger.warning(f"[카드뉴스] 고정값 사전 주입 실패: {e}")
    try:
        from ai_briefing import _facts_block as _briefing_facts
        fb = _briefing_facts()
        if fb:
            parts.append(fb)
    except Exception as e:
        logger.warning(f"[카드뉴스] 팩트사전 주입 실패: {e}")
    return "\n\n".join(parts)


def _clean_bullets(raw, desc: str | None) -> list[str]:
    """요점 3개 정규화 — 모델이 누락하면 desc 문장으로 폴백(v3 템플릿 호환)."""
    out = []
    if isinstance(raw, list):
        out = [str(b).strip().lstrip("•▪·-– ").strip() for b in raw if str(b).strip()]
    if len(out) < 3 and desc:
        for sent in [x.strip() for x in str(desc).replace("!", ".").split(".") if x.strip()]:
            if len(out) >= 3:
                break
            if sent not in out:
                out.append(sent[:25])
    return out[:3]


def _issues_text(issues: list[dict]) -> str:
    """고정값 대조·미리보기용 카드 텍스트 전문 (제목/부제/요점/설명)."""
    blocks = []
    for i, it in enumerate(issues, 1):
        lines = [f"[{i}] ({it.get('cat','')}) {it.get('title','')}"]
        if it.get("subtitle"):
            lines.append(f"  · {it['subtitle']}")
        for b in it.get("bullets") or []:
            lines.append(f"  ▪ {b}")
        if it.get("desc"):
            lines.append(f"  {it['desc']}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def collect_aesa_top3(limit: int = NUM_WORLD) -> list[dict]:
    """해외뉴스방 외신 큐레이션과 동일 소스에서 상위 기사 조회.

    aesa_content_report(매일 07:00 발송)와 같은 윈도우(전날 00:00~23:59 KST,
    score>=7)를 같은 DB(aesa_articles)에서 직접 조회한다. 데이터는 자정에
    확정되므로 06:00 카드뉴스 생성 시점에도 07:00 발송분과 동일한 풀이다.
    실패/기사 없음 시 빈 리스트 → 카드뉴스는 외신 없이 12장으로 폴백.
    """
    try:
        from datetime import timedelta
        from app import create_app
        from app.models.aesa_article import AesaArticle
        _app = create_app()
        with _app.app_context():
            now = datetime.now()
            y_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            y_end = y_start.replace(hour=23, minute=59, second=59)
            rows = AesaArticle.query.filter(
                AesaArticle.created_at >= y_start,
                AesaArticle.created_at <= y_end,
                AesaArticle.score >= 7,
            ).order_by(AesaArticle.score.desc(), AesaArticle.id.desc()).limit(limit).all()
            arts = [{
                "title": a.title,
                "source": a.source,
                "score": a.score,
                "summary": a.summary or "",
                "lenses": a.lenses or "",
                "korea_insight": a.korea_insight or "",
            } for a in rows]
        logger.info(f"[카드뉴스] 외신 {len(arts)}건 수집 (전날 score>=7 상위)")
        return arts
    except Exception as e:
        logger.warning(f"[카드뉴스] 외신 수집 실패({e}) — 외신 카드 생략")
        return []


def _build_world_section(world_articles: list[dict]) -> tuple[str, str, str]:
    """외신 기사 목록 → PROMPT 삽입 조각(world_intro, world_section, world_count_note)."""
    if not world_articles:
        return "", "", ""
    k = len(world_articles)
    lines = []
    for i, a in enumerate(world_articles, 1):
        lens = f" [렌즈 {a['lenses']}]" if a.get("lenses") else ""
        insight = f"\n   한국 시사점: {a['korea_insight']}" if a.get("korea_insight") else ""
        lines.append(f"{i}. ({a['source']}, {a['score']}/10점{lens}) {a['title']}\n"
                     f"   요약: {a['summary']}{insight}")
    section = (
        f"[오늘의 외신 TOP{k} — 국내 {NUM_ISSUES}개 뒤에 이어붙일 것]\n"
        f"아래 {k}건은 해외뉴스방 큐레이션 기사입니다. 주어진 순서 그대로\n"
        f'cat="외신", tier="world" 카드 {k}장으로 작성하세요 (issues 배열의 마지막 {k}개).\n'
        f"- title/desc: 한국 독자 관점으로. desc에는 '한국 시사점'이 제공된 경우 반드시 녹일 것.\n"
        f"- image_prompt: 외신 카드는 해당 국가의 인물·배경을 그대로 사용\n"
        f"  (예: 미국 뉴스면 American people, 일본 뉴스면 Japanese setting).\n"
        f"  단, 실존 인물의 얼굴을 특정하지 말고 익명 인물로. 글자 금지 규칙 동일.\n"
        f"- 국내 10개 이슈가 이 외신과 같은 사건을 다루면 국내 쪽을 다른 이슈로 대체할 것.\n\n"
        f"[외신 기사 목록]\n" + "\n".join(lines) + "\n\n"
    )
    intro = f" 외신 카드 {k}장도 함께 작성합니다."
    count_note = f" + 외신 {k}개"
    return intro, section, count_note


def select_issues(briefing_text: str, n: int = NUM_ISSUES,
                  world_articles: list[dict] | None = None) -> list[dict]:
    """브리핑(+외신 목록) → 카드용 이슈(제목·설명·장면 프롬프트 포함)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if anthropic is None:
        raise ImportError("anthropic 패키지가 설치되지 않았습니다.")

    world_articles = world_articles or []
    total = n + len(world_articles)
    world_intro, world_section, world_count_note = _build_world_section(world_articles)

    # 13개 이슈 × (점수+설명+장면프롬프트)는 출력이 커서 넉넉한 타임아웃/토큰 필요
    client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=2)
    prompt_text = PROMPT.format(
        n=n, total=total, briefing=briefing_text,
        world_intro=world_intro, world_section=world_section,
        world_count_note=world_count_note, facts_block=_facts_block(),
    )
    # JSON 파싱 실패(따옴표 이스케이프 누락 등) 시 1회 재요청 — 8/4 실측 사례 대응
    data = None
    for attempt in (1, 2):
        resp = client.messages.create(
            model=SELECT_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt_text}],
        )
        try:
            data = _extract_json(resp.content[0].text)
            break
        except (json.JSONDecodeError, ValueError) as je:
            logger.warning(f"[카드뉴스] 이슈 JSON 파싱 실패({attempt}/2): {je}")
            if attempt == 2:
                raise

    issues = []
    for it in (data.get("issues") or [])[:total]:
        cat = (it.get("cat") or "기타").strip()
        if cat not in VALID_CATS:
            cat = "기타"
        tier = (it.get("tier") or "").strip()
        if tier not in TIER_LABELS:
            tier = "core"
        # 외신 일관성 강제: tier=world ↔ cat=외신
        if tier == "world":
            cat = "외신"
        elif cat == "외신":
            tier = "world"
        try:
            score = max(0, min(100, int(it.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        issues.append({
            "cat": cat,
            "tier": tier,
            "score": score,
            "title": (it.get("title") or "").strip(),
            "subtitle": (it.get("subtitle") or "").strip(),
            "bullets": _clean_bullets(it.get("bullets"), it.get("desc")),
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


def _template():
    """카드 템플릿 선택 — CARDNEWS_TEMPLATE=v4(위계형·그라데이션) / 기본 v3.
    v4 는 샘플 승인 후 기본값으로 전환한다."""
    if os.environ.get("CARDNEWS_TEMPLATE", "v3").lower() == "v4":
        from cardnews_v4 import build_html as b4, hero_for as h4
        return "v4", b4, h4
    return "v3", build_html, _hero_for


def _publish_target() -> str | None:
    """/card_ok 발행 대상 채팅 — CARDNEWS_CHANNEL_ID 우선, 없으면 브리핑방(TELEGRAM_CHAT_ID)."""
    return os.environ.get("CARDNEWS_CHANNEL_ID") or os.environ.get("TELEGRAM_CHAT_ID")


def generate_daily_cardnews(briefing_text: str,
                            chat_id: str | None = None,
                            world_articles: list[dict] | None = None,
                            source: str = "") -> tuple[list[str], bool]:
    """브리핑 최종본 → 15장(표지+국내10+외신3+엔딩) 생성 → **관리자 미리보기 DM** → 초안 대기.

    발행은 하지 않는다. 관리자가 미리보기(카드 앨범 + 텍스트 전문 + 고정값 대조 결과)를
    확인하고 /card_ok 를 보내야 publish_card_draft() 가 채널로 내보낸다.
    이미지는 정정이 어려우므로 자동발행 금지(2026-09-16 교섭단체 30석·천하람 소속 오류 민원).

    source: 호출부가 입력 출처를 명시 — 'verified_briefing'(발송 직후 최종본) 또는
            'db_briefing'(DB 저장분 = verify_pass·레이아웃 적용 후 저장된 최종본).
            그 외 값(원문 피드 등)은 거부한다.
    world_articles: 외신 기사 목록. None이면 DB에서 자동 수집(프로덕션 경로).

    반환: (PNG 경로 목록, 미리보기 전송 성공 여부).
    """
    if source not in ("verified_briefing", "db_briefing"):
        raise ValueError(f"카드뉴스 입력 출처 거부: {source!r} — verify_pass 통과 최종본만 허용")
    if world_articles is None:
        world_articles = collect_aesa_top3()

    issues = select_issues(briefing_text, world_articles=world_articles)

    # 카드 표시 정보 주입 (템플릿은 tier_label/display_no만 참조)
    #  - 국내 카드: 01~10, 외신 카드: 별도로 01~03 재시작
    domestic_no = world_no = 0
    for iss in issues:
        iss["tier_label"] = TIER_LABELS.get(iss.get("tier", ""), "")
        if iss.get("cat") == "외신":
            world_no += 1
            iss["display_no"] = world_no
        else:
            domestic_no += 1
            iss["display_no"] = domestic_no

    # 고정값 사전 대조 — 위반 시 초안은 만들되 '발행 보류' 표시 (/card_ok 거부)
    violations = []
    try:
        from fixed_facts import check_text
        violations = check_text(_issues_text(issues))
        if violations:
            logger.warning(f"[카드뉴스] 고정값 불일치 {len(violations)}건 — 발행 보류: "
                           + ", ".join(v["id"] for v in violations))
    except Exception as e:
        logger.warning(f"[카드뉴스] 고정값 대조 실패(보류 없이 진행): {e}")

    tpl_name, _build_html, _hero = _template()

    # 장면 일러스트 생성 (실패한 장은 플레이스홀더로 대체되어 렌더는 계속)
    # 요청 간격 12초: 무결제 계정 분당 6건 제한 대응 (결제 등록 후에도 무해)
    import time
    heros = []
    for i, iss in enumerate(issues, 1):
        logger.info(f"[카드뉴스] 일러스트 {i}/{len(issues)} 생성 중… {iss['scene_ko'][:30]}")
        if i > 1:
            time.sleep(12)
        heros.append(_hero(iss))

    now = datetime.now(KST)
    html = _build_html(issues, heros, now.strftime("%Y.%m.%d"))

    out_dir = os.path.join(_HERE, "output", "cardnews", now.strftime("%Y-%m-%d"))

    # 재합성용 원본 보존: 일러스트 PNG + 이슈 JSON.
    # 템플릿(푸터·문구·간격)만 바뀔 때 Flux 재호출 없이 0원으로 다시 합성할 수 있다.
    try:
        import base64 as _b64
        raw_dir = os.path.join(out_dir, "illustrations")
        os.makedirs(raw_dir, exist_ok=True)
        for i, uri in enumerate(heros, 1):
            if uri and uri.startswith("data:image/png;base64,"):
                with open(os.path.join(raw_dir, f"{i:02d}.png"), "wb") as f:
                    f.write(_b64.b64decode(uri.split(",", 1)[1]))
        with open(os.path.join(out_dir, "issues.json"), "w", encoding="utf-8") as f:
            json.dump(issues, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[카드뉴스] 원본 보존 실패(렌더는 계속): {e}")

    paths = render_cards(html, out_dir)

    target = chat_id or os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
    caption = f"🗞️ 누렁이 카드뉴스 · {now.strftime('%Y년 %m월 %d일')}"

    failed = sum(1 for h in heros if not h)
    preview_caption = f"🔍 [미리보기] {caption} ({len(paths)}장·{tpl_name})"
    if failed:
        preview_caption += f" ⚠️ 일러스트 {failed}장 실패"

    # 초안 저장 — /card_ok 가 이 상태를 읽어 발행. 파일은 워커 컨테이너 디스크에 있으므로
    # 재배포 후에는 /cardnews 로 다시 생성해야 한다.
    draft = {
        "date": now.strftime("%Y-%m-%d"), "created_at": now.isoformat(),
        "paths": paths, "caption": caption, "template": tpl_name,
        "violations": violations, "failed_illust": failed,
        "text": _issues_text(issues),
    }
    try:
        from g2b_tracker import state_set
        state_set(DRAFT_STATE_KEY, json.dumps(draft, ensure_ascii=False))
    except Exception as e:
        logger.error(f"[카드뉴스] 초안 상태 저장 실패 — /card_ok 불가, 재생성 필요: {e}")

    # 미리보기: (1) 카드 앨범 → 관리자 DM, (2) 텍스트 전문 + 고정값 대조 + 승인 안내
    sent = send_cards_to_telegram(paths, target, caption=preview_caption)
    try:
        from fixed_facts import format_violations
        verdict = format_violations(violations)
    except Exception:
        verdict = ""
    pub = _publish_target() or "(미설정 — CARDNEWS_CHANNEL_ID 또는 TELEGRAM_CHAT_ID 필요)"
    head = (f"🔍 <b>[미리보기] 누렁이 카드뉴스</b> {now.strftime('%m/%d')} · {len(paths)}장 · 템플릿 {tpl_name}\n"
            f"발행 대상: {pub}\n{verdict}\n"
            + ("승인: /card_ok · 폐기: /card_no" if not violations
               else "보류 상태 — 수정 후 /cardnews 재생성 권장 · 강행: /card_ok force · 폐기: /card_no")
            + "\n\n")
    body = draft["text"]
    try:
        from ai_briefing import _split_text
        chunks = _split_text(head + body, limit=4000)
    except Exception:
        chunks = [(head + body)[:4000]]
    for ch in chunks:
        try:
            from app.utils.telegram_notify import send_telegram_message
            send_telegram_message(ch, chat_id=target)
        except Exception as e:
            logger.warning(f"[카드뉴스] 미리보기 텍스트 전송 실패: {e}")

    if not sent:
        logger.error("[카드뉴스] 미리보기 앨범 전송 최종 실패 — 관리자 알림 발송")
        _notify_admin(
            "❌ <b>카드뉴스 미리보기 전송 실패</b>\n\n"
            f"{len(paths)}장 생성은 완료됐으나 텔레그램 업로드가 실패했습니다.\n"
            "/cardnews 로 재시도할 수 있습니다."
        )
    return paths, sent


def publish_card_draft(force: bool = False) -> str:
    """/card_ok — 미리보기 승인된 초안을 발행 채널로 전송. 고정값 불일치 시 force 없이는 거부."""
    try:
        from g2b_tracker import state_get, state_set
        raw = state_get(DRAFT_STATE_KEY)
        if not raw or raw == "null":
            return "⚠️ 발행 대기 중인 카드뉴스 초안이 없습니다. /cardnews 로 생성하세요."
        draft = json.loads(raw)
        if draft.get("violations") and not force:
            ids = ", ".join(v["id"] for v in draft["violations"])
            return (f"🚫 고정값 불일치({ids})로 발행 보류 상태입니다.\n"
                    "수정 후 /cardnews 재생성을 권장합니다. 그래도 내보내려면 /card_ok force")
        paths = [p for p in draft.get("paths", []) if os.path.exists(p)]
        if len(paths) != len(draft.get("paths", [])):
            state_set(DRAFT_STATE_KEY, "null")
            return ("⚠️ 초안 이미지 파일이 없습니다(재배포로 소실). /cardnews 로 다시 생성하세요.")
        target = _publish_target()
        if not target:
            return "⚠️ 발행 대상 미설정 — CARDNEWS_CHANNEL_ID(또는 TELEGRAM_CHAT_ID) 환경변수 필요."
        sent = send_cards_to_telegram(paths, target, caption=draft.get("caption", ""))
        if not sent:
            return "❌ 채널 전송 실패 — 초안은 유지됩니다. 잠시 후 /card_ok 재시도."
        state_set(DRAFT_STATE_KEY, "null")
        note = " (⚠️ 고정값 불일치 강행)" if draft.get("violations") else ""
        return f"✅ 카드뉴스 {len(paths)}장 발행 완료 → {target}{note}"
    except Exception as e:
        logger.error(f"[카드뉴스] 발행 실패: {e}", exc_info=True)
        return f"❌ 발행 실패: {e}"


def discard_card_draft() -> str:
    """/card_no — 초안 폐기 (이미지 파일은 남겨 둔다)."""
    try:
        from g2b_tracker import state_set
        state_set(DRAFT_STATE_KEY, "null")
    except Exception as e:
        return f"❌ 폐기 실패: {e}"
    return "🗑 카드뉴스 초안 폐기 완료."


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
        paths, sent = generate_daily_cardnews(
            text, source="verified_briefing" if morning_briefing else "db_briefing")
        if sent:
            logger.info(f"[카드뉴스] 완료 ✅ ({len(paths)}장 생성·미리보기 전송, /card_ok 대기)")
        else:
            logger.error(f"[카드뉴스] 생성 {len(paths)}장 완료, 미리보기 전송 실패 ❌ (관리자 알림 발송됨)")
    except Exception as e:
        logger.error(f"[카드뉴스] 생성 실패(브리핑 발송에는 영향 없음): {e}", exc_info=True)
        _notify_admin(
            f"❌ <b>카드뉴스 자동 생성 실패</b>\n\n"
            f"오류: {str(e)[:300]}\n\n"
            f"브리핑 발송은 정상입니다. /cardnews 로 수동 재시도할 수 있습니다."
        )


if __name__ == "__main__":
    run_daily_cardnews_safe()
