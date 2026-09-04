"""
ai_briefing.py — 누렁이 생태계 AI 브리핑 모듈 (v2.0)

sent_news.json 의존 없이 브리핑 시점에 RSS 직접 크롤링.
Claude Haiku API로 4개 분야 요약 후 텔레그램 전송.

호출: scheduler_worker.py → send_briefing()
스케줄: 매일 06:00 / 18:00 KST
"""

import os
import re
import json
import logging
import feedparser
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

try:
    import anthropic
except ImportError:
    anthropic = None

# ── 로깅 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_briefing")

# ── 상수 ──────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_ARTICLES_PER_CATEGORY = 15
# 고밀도 1줄(120~200자) × 4분야 × 5~6항목 기준으로 산정
BRIEFING_MIN_CHARS = 1500
BRIEFING_MAX_CHARS = 2500
TELEGRAM_MAX_LENGTH = 4096

# ── 암호화폐 시세 (Upbit, 무인증) ─────────────────
UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker"
CRYPTO_MARKETS = ["KRW-BTC", "KRW-ETH"]
CRYPTO_NAMES = {"KRW-BTC": "비트코인", "KRW-ETH": "이더리움"}

# ── RSS 피드 설정 (카테고리별) ────────────────────
RSS_FEEDS = {
    "정치/시사": [
        "https://news.google.com/rss/headlines/section/topic/NATION?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "경제/산업": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "AI/기술": [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "기타(스포츠/연예)": [
        "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ko&gl=KR&ceid=KR:ko",
    ],
}

# ── 환경변수 ──────────────────────────────────────
def _env(key: str) -> str | None:
    return os.environ.get(key)


# ══════════════════════════════════════════════════
#  1. 시간대 계산
# ══════════════════════════════════════════════════
def get_time_window() -> tuple[datetime, datetime, str]:
    """
    브리핑 시점에 따라 뉴스 수집 시간대를 결정.
    - 아침 브리핑(06:00): 전날 18:00 ~ 당일 06:00
    - 저녁 브리핑(18:00): 당일 06:00 ~ 당일 18:00
    """
    now = datetime.now(KST)

    if now.hour < 12:
        # 아침 브리핑
        start = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        end = now.replace(hour=6, minute=0, second=0, microsecond=0)
        period = "🌅 아침"
    else:
        # 저녁 브리핑
        start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        end = now.replace(hour=18, minute=0, second=0, microsecond=0)
        period = "🌆 저녁"

    return start, end, period


# ══════════════════════════════════════════════════
#  2. RSS 뉴스 수집
# ══════════════════════════════════════════════════
def _parse_pub_date(entry) -> datetime | None:
    """RSS entry에서 발행 시각을 KST datetime으로 파싱."""
    # 방법 1: published 문자열 직접 파싱 (RFC 2822)
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return dt.astimezone(KST)
        except Exception:
            pass

    # 방법 2: feedparser의 *_parsed 튜플
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                from calendar import timegm
                ts = timegm(parsed)
                return datetime.fromtimestamp(ts, tz=KST)
            except Exception:
                pass

    return None


def fetch_news_by_category(
    start_time: datetime,
    end_time: datetime,
) -> dict[str, list[dict]]:
    """카테고리별 RSS 뉴스를 수집하고 시간 필터링."""
    categorized: dict[str, list[dict]] = {}

    for category, feed_urls in RSS_FEEDS.items():
        articles: list[dict] = []

        for url in feed_urls:
            try:
                feed = feedparser.parse(url)
                if feed.bozo and not feed.entries:
                    logger.warning(f"RSS 파싱 경고 [{category}]: {url}")
                    continue

                for entry in feed.entries:
                    pub = _parse_pub_date(entry)

                    # 발행일 없는 기사는 무조건 제외 (구식 기사 혼입 방지)
                    if pub is None:
                        continue

                    # 시간 필터: 커버리지 윈도우 밖이면 제외
                    if pub < start_time or pub > end_time:
                        continue

                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue

                    # 중복 제거 (같은 제목)
                    if any(a["title"] == title for a in articles):
                        continue

                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": pub.isoformat() if pub else None,
                    })

            except Exception as e:
                logger.warning(f"RSS 수집 실패 [{category}] {url}: {e}")

        categorized[category] = articles[:MAX_ARTICLES_PER_CATEGORY]
        logger.info(f"  [{category}] {len(categorized[category])}건 수집")

    return categorized


# ══════════════════════════════════════════════════
#  2.5. 암호화폐 시세 수집 (Upbit, 무인증)
# ══════════════════════════════════════════════════
def fetch_crypto_prices() -> str | None:
    """Upbit에서 BTC/ETH 현재가를 가져와 한 줄 문자열로 반환.

    실패(네트워크/비200/파싱/유효 시세 없음) 시 None을 반환하여
    호출부에서 시세 줄을 통째로 생략(폴백)하도록 한다.
    """
    try:
        resp = requests.get(
            UPBIT_TICKER_URL,
            params={"markets": ",".join(CRYPTO_MARKETS)},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"[시세] Upbit 비정상 응답: HTTP {resp.status_code}")
            return None
        data = resp.json()
    except Exception as e:
        logger.warning(f"[시세] Upbit 조회 실패: {e}")
        return None

    by_market = {t.get("market"): t for t in data if isinstance(t, dict)}
    parts: list[str] = []
    for market in CRYPTO_MARKETS:
        t = by_market.get(market)
        if not t:
            continue
        try:
            price = int(round(float(t["trade_price"])))
            rate = float(t["signed_change_rate"]) * 100
        except (KeyError, TypeError, ValueError):
            continue
        name = CRYPTO_NAMES.get(market, market)
        parts.append(f"{name} {price:,}원({rate:+.1f}%)")

    if not parts:
        logger.warning("[시세] Upbit 응답에서 유효한 시세를 찾지 못함")
        return None

    return "📈 시세(Upbit 기준): " + " · ".join(parts)


# ══════════════════════════════════════════════════
#  2.8. 팩트체크 강화 — 시스템 프롬프트 3블록
#       (확정 팩트 사전 / 생성 검증 규칙 / 최근 브리핑 이력)
# ══════════════════════════════════════════════════
FACTS_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "facts.json")

# 반복 오류 5종(인명·직함, 시제 승격, 논조 반전, 별건 결합, 자기 이력 미참조) 차단 규칙.
# 지시문 원문 그대로 — 문구 수정 금지.
VERIFICATION_RULES = """[생성 검증 규칙 — 위반 시 해당 항목을 다시 쓸 것]
1. 시제 승격 금지: 원문이 "상정·추진·거론·예정·검토·전망"이면 결과 표현("통과·출범·확정·가결·선정")으로 바꾸지 말 것.
2. 논조 보존: 각 기사를 먼저 [비판·폭로 / 성과·미담 / 중립]으로 분류하고, 분류와 반대 방향의 서술을 금지할 것. (예: 징계·구속 대상자가 과거에 받은 표창은 비판 기사임)
3. 별건 결합 금지: 서로 다른 두 사건을 "~로 발전했다", "~에 이어" 등 인과·연속 관계로 묶지 말 것. 같은 지역·기관이라도 별건은 별개 문장으로.
4. 인명·직함: 확정 팩트 사전과 대조할 것. 사전에 없는 인물의 직함이 불확실하면 인명을 빼고 직명만 쓸 것. 실존 인물의 소속 정당·직책을 추측으로 채우지 말 것.
5. 통계·여론조사: 조사기관과 조사기간을 병기할 것. 둘 중 하나라도 원문에 없으면 "~로 전해졌다"로 완곡 처리할 것.
6. 섹션 배치: 금리·물가·환율·증시·코인 시세는 경제/산업 섹션에, 기술 제품·서비스·연구는 AI/기술 섹션에 배치할 것.
7. 최근 브리핑 정합성: 함께 제공되는 [최근 브리핑 이력]과 모순되는 서술(이미 가결된 안건의 "촉구" 등)을 금지할 것. 동일 뉴스가 이틀 넘게 재등장하면 최초 발생 날짜를 명시할 것.
8. 숫자 재검: 인원수·연도·배수는 원문에서 그대로 옮기고, 두 숫자가 섞일 수 있는 문맥(사망자 vs 실종자 등)이면 주체를 명시할 것."""


def _facts_block() -> str:
    """facts.json → [확정 팩트 사전] 블록. 로드 실패 시 빈 문자열(브리핑은 계속)."""
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            raw = f.read().strip()
        return (
            "[확정 팩트 사전 — 아래 내용과 충돌하는 서술은 절대 생성하지 말 것.\n"
            "인물의 직함은 반드시 이 사전을 따르고, 사전에 없는 인물은 이름 대신 직명만 쓸 것]\n"
            f"{raw}"
        )
    except Exception as e:
        logger.warning(f"[팩트사전] facts.json 로드 실패 — 사전 없이 진행: {e}")
        return ""


def _recent_briefings_block(days: int = 7, max_items: int = 7,
                            char_budget: int = 1400) -> str:
    """최근 7일 발행 브리핑을 [최근 브리핑 이력] 블록으로 요약.

    char_budget=1400자: 한글 토큰화(자당 ~1.5토큰) 기준 총 2,000토큰 예산 준수.
    조회 실패 시 빈 문자열 반환(브리핑 생성은 계속).
    경로 1) Flask 앱 컨텍스트 ORM(프로덕션) → 2) DATABASE_URL 직접 조회(드라이런 폴백)
    """
    rows: list[tuple] = []  # (created_at, briefing_type, title, content)
    try:
        from app import create_app
        from app.models.briefing import Briefing
        _app = create_app()
        with _app.app_context():
            since = datetime.now(KST).replace(tzinfo=None) - timedelta(days=days)
            for b in (Briefing.query.filter(Briefing.created_at >= since)
                      .order_by(Briefing.created_at.desc()).limit(max_items).all()):
                rows.append((b.created_at, b.briefing_type, b.title or "", b.content or ""))
    except Exception as e:
        db_url = _env("DATABASE_URL")
        if db_url:
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                cur = conn.cursor()
                cur.execute(
                    "SELECT created_at, briefing_type, title, content FROM briefings "
                    "WHERE created_at >= NOW() - INTERVAL '%s days' "
                    "ORDER BY created_at DESC LIMIT %s", (days, max_items))
                rows = [(r[0], r[1], r[2] or "", r[3] or "") for r in cur.fetchall()]
                conn.close()
            except Exception as e2:
                logger.warning(f"[브리핑이력] 조회 실패(생략하고 진행): app={e} / db={e2}")
                return ""
        else:
            logger.warning(f"[브리핑이력] 조회 실패(생략하고 진행): {e}")
            return ""

    if not rows:
        return ""

    lines, used = [], 0
    for created, btype, title, content in rows:
        # 요약 캐시 없음 → 제목 줄 + 본문 앞부분(공백 정리)으로 300자 이내 요약
        head = " ".join((title or content.split("\n")[0]).split())[:80]
        body = " ".join(content.split())[:180]
        item = f"- {created:%m/%d} {btype}: {head} | {body}"[:300]
        if used + len(item) > char_budget:
            break
        lines.append(item)
        used += len(item)

    if not lines:
        return ""
    return ("[최근 브리핑 이력 — 최신순. 아래와 모순되는 서술 금지.\n"
            "팩트 정합성 대조용으로만 사용 — 아래 이력의 문체·문장 구조·항목 길이는\n"
            "절대 모방하지 말 것(작성 규칙의 고밀도 1줄 형식이 항상 우선)]\n"
            + "\n".join(lines))


def build_briefing_system_prompt() -> str:
    """팩트 사전 + 검증 규칙 + 최근 이력을 시스템 프롬프트로 조립."""
    facts = _facts_block()
    history = _recent_briefings_block()
    system = "\n\n".join(p for p in (facts, VERIFICATION_RULES, history) if p)
    logger.info(
        f"[검증패치] 시스템 프롬프트 조립 — 팩트사전 {len(facts)}자 · "
        f"규칙 {len(VERIFICATION_RULES)}자 · 이력 {len(history)}자 · 총 {len(system)}자"
    )
    return system


# ══════════════════════════════════════════════════
#  3. Claude Haiku로 브리핑 생성
# ══════════════════════════════════════════════════
def generate_briefing_with_ai(
    categorized_news: dict[str, list[dict]],
    period: str,
    crypto_line: str | None = None,
) -> str | None:
    """수집된 헤드라인을 Claude Haiku에게 보내 브리핑 생성."""
    api_key = _env("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if anthropic is None:
        raise ImportError("anthropic 패키지가 설치되지 않았습니다. pip install anthropic")

    # 헤드라인 텍스트 조합
    news_block = ""
    total_count = 0
    for cat, articles in categorized_news.items():
        news_block += f"\n[{cat}]\n"
        for a in articles:
            news_block += f"- {a['title']}\n"
            total_count += 1

    if total_count == 0:
        return None

    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")

    time_str = "06:00" if "아침" in period else "18:00"

    # 팩트 컨텍스트 자동 주입
    try:
        from fact_checker import get_fact_context
        fact_context = get_fact_context()
    except Exception:
        fact_context = ""

    # 시세 블록 (있을 때만 — 폴백 시 통째로 생략)
    if crypto_line:
        crypto_context = (
            "[시세 데이터 — 아래 수치를 그대로(반올림·변형 없이) 사용하고, "
            "💰 경제/산업 섹션의 마지막 줄에 이 줄을 그대로 포함]\n"
            f"{crypto_line}\n"
        )
    else:
        crypto_context = ""

    prompt = f"""{fact_context}당신은 '누렁이 정보공유방'의 뉴스 브리핑 AI입니다.
아래 뉴스 헤드라인들을 바탕으로 {period} 브리핑을 작성하세요.

[작성 규칙]
1. 첫 줄(제목): "{period} 누렁이 정보공유방 브리핑 | {today_str} {time_str}"
2. 제목 바로 다음 줄에 출처 헤더:
   출처: https://t.me/gazzzza2025
   (실시간 텔레그램 정보방)
3. 한 줄 빈 줄 후 4개 분야(🏛️ 정치/시사, 💰 경제/산업, 🤖 AI/기술, 🎯 기타) 시작
4. [포맷] 각 분야별 핵심 내용은 ▪ 고밀도 1줄 항목으로 작성:
   - [줄 규칙 — 최우선] 각 ▪ 항목은 반드시 '새 줄'에서 시작하고,
     ▪ 항목과 다음 ▪ 항목 사이에 빈 줄을 넣지 말 것(연속된 줄로 붙일 것).
     섹션 제목 바로 다음 줄에서 첫 ▪ 가 시작됨. 한 줄에 ▪ 두 개 이상 금지.
     맥락 줄("→")도 절대 쓰지 말 것.
   - [항목 길이 — 줄 규칙 다음으로 중요] 한 항목은 1~3문장,
     공백 포함 120~200자. 120자 미만의 짧은 헤드라인형 항목은 규칙 위반.
     늘어난 분량은 해석이 아니라 '팩트'로 채울 것: 행위 주체·기관명,
     구체 수치, 경위, 후속 절차(항소 예고·투표 예정·발표 일정 등).
     (총량을 맞추기 위해 항목을 짧게 줄이지 말고, 분야당 5개 기준으로
      항목당 120~140자를 유지하면 전체 규칙과 자연히 맞음)
   - [문체] 통신사 데스크 톤 — 명사형·음슴체 종결, 건조하고 전문적으로.
     해설·전망성 술어는 어떤 활용형으로도 절대 금지:
     '풀이되-', '해석되-', '기대되-', '예상되-', '평가되-', '전망되-',
     '~것으로 보임/보인다', '~ 주목', '~ 관심사'
     (예: "예상된다" 뿐 아니라 "예상되자", "예상돼" 등 전부 금지).
     주체 없는 '전망', '관측', '분위기' 서술도 금지.
     "역대급", "충격" 등 장식 형용사 금지.
     전망·평가는 발화 주체가 명시된 인용으로만 쓸 것
     (예: 리얼미터는 오차범위 내 접전이라고 분석했음).
     결측 표기 절대 금지: '미상', '미정', '미확인', '알려지지 않음' 등
     정보가 없다는 서술을 쓰지 말 것 — 정보가 없으면 그 절 자체를 삭제하고
     확인된 사실만으로 문장을 구성할 것
     (예: "사고 원인은 미상"이라 쓰지 말고 원인 절을 통째로 뺄 것).
   - 분야당 정확히 5개 항목 (마지막 '기타' 분야도 동일 형식으로 완결)
   - 같은 분야 안의 ▪ 항목 줄들은 빈 줄 없이 연속. 빈 줄은 섹션 사이 한 줄만.
     아래는 형식·길이·문체의 기준 예시 — 각 항목이 이 예시만큼 길어야 함:
     🏛️ 정치/시사
     ▪ 국회 법제사법위원회가 A법 개정안을 재석 15인 중 찬성 9인으로 의결했음. 야당 의원 6인은 표결 직전 퇴장했으며, 법안은 이번 주 본회의에 상정될 예정. 국회 사무처는 처리 시한을 다음 달 10일로 공지했음.
     ▪ 감사원이 B부처 정기감사에서 예산 12억 원의 집행 부적정 사례 3건을 통보했음. 해당 부처는 관련자 2명에 대한 징계 절차에 착수했다고 밝혔음.

     💰 경제/산업
     ▪ 한국은행이 기준금리를 연 3.00%로 동결했음. 금통위원 7인 중 6인이 동결에 표를 던졌으며, 다음 금통위는 10월 열릴 예정.
5. 전체 글자 수: {BRIEFING_MIN_CHARS}~{BRIEFING_MAX_CHARS}자 (한글 기준, 반드시 준수)
6. 공식적이지만 친근한 톤, 각 분야(섹션)는 빈 줄 하나로 구분
7. 모든 분야의 모든 문장은 반드시 완결된 형태로 끝나야 합니다 (절대 문장 중간에 끊기지 않도록)
8. 마지막 분야 요약이 끝난 후 빈 줄을 넣고 출처 푸터:
   출처: https://buly.kr/7mBN720
   (실시간 카카오톡 오픈채팅)
9. 제공된 헤드라인이 적더라도 반드시 브리핑을 작성하세요. 헤드라인 제목만으로 충분히 요약 가능합니다.
10. "정보가 부족합니다", "브리핑을 작성할 수 없습니다" 같은 거부 메시지는 절대 출력하지 마세요. 어떤 상황에서든 반드시 브리핑 형식으로 작성하세요.
11. 특정 분야 기사가 없으면 해당 분야는 "주요 보도 없음"으로 짧게 언급하고 다음 분야로 넘어가세요.
12. [팩트 정확도] 헤드라인에 명시된 내용만 요약하세요. 헤드라인에 없는 감정, 반응, 발언을 지어내지 마세요. 예: "OO 열애설" 헤드라인 → "열애설이 보도됐다"까지만. "심기불편", "분노" 등 추측성 표현 절대 금지.
13. [시의성] 제공된 헤드라인은 모두 오늘자입니다. "최근", "지난달" 등 모호한 시점 대신 "오늘", "금일" 기준으로 작성하세요.
14. [수치·날짜 임의생성 금지] 팩트 컨텍스트와 [시세 데이터]로 제공된 값 외에는 구체적 수치(가격·지수·통계·퍼센트), 날짜, 인과관계('~때문에', 'A가 B를 초래')를 지어내지 마세요. 헤드라인에 숫자가 없으면 숫자를 쓰지 말고, 제공되지 않은 시세·지표는 언급하지 마세요.
15. [섹션 고정] 암호화폐·코인 관련 항목(시세·ETF·규제·거래소 포함)은 예외 없이 💰 경제/산업 섹션에만 배치하세요. AI/기술·기타 섹션에 두지 마세요.

{crypto_context}[오늘의 뉴스 헤드라인]
{news_block}"""

    client = anthropic.Anthropic(api_key=api_key)

    # 팩트체크 강화: 확정 팩트 사전 + 생성 검증 규칙 + 최근 브리핑 이력을 시스템 프롬프트로.
    # 조립 실패가 브리핑 생성을 막지 않도록 방어 (블록별 실패는 각 함수가 이미 흡수).
    try:
        system_prompt = build_briefing_system_prompt()
    except Exception as sys_err:
        logger.warning(f"[검증패치] 시스템 프롬프트 조립 실패 — 없이 진행: {sys_err}")
        system_prompt = ""

    kwargs = {"system": system_prompt} if system_prompt else {}
    # 2줄 구조로 본문이 최대 3,000자(≈4,500토큰) — 2048이면 잘림(과거 사고 전례)
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )

    text = _normalize_bullet_spacing(response.content[0].text.strip())
    # 문체·길이 회귀 방어: 해설 술어·200자 초과 항목만 1회 재작성 (실패 시 원문 유지)
    text = _enforce_density(text, client, system_prompt)
    # 시세 줄 경제 섹션 고정 (결정론 후처리 — 모델이 다른 섹션에 둬도 교정)
    text = _pin_crypto_line(text, crypto_line)
    logger.info(f"AI 브리핑 생성 완료 — {len(text)}자")
    return text


# 해설·전망성 술어 + 결측 표기 회귀 감지 (전 활용형) — 프롬프트 금지 목록과 동일 범위.
# '되/돼/된/됨/될'을 별도 나열: '됨'(U+B428) 등 합성 음절은 '되' 부분 문자열 매칭 불가.
# 결측 표기 가드: '의미상'·'미정산'·인명(김미정 등) 오탐 방지 lookaround —
# 오탐이어도 삭제가 아닌 재작성 요청이라 안전(모델이 규칙에 맞게 판단).
BANNED_PREDICATE_RE = re.compile(
    r"(?:풀이|해석|기대|예상|평가|전망)(?:되|돼|된|됨|될)|것으로 보|주목|관심사"
    r"|(?<!의)미상|(?<![가-힣])미정(?!산)|미확인|알려지지 않|확인되지 않")
MAX_ITEM_CHARS = 200

REWRITE_PROMPT = """다음 뉴스 브리핑 항목들이 문체 규칙을 위반했다. 각 항목을 규칙에 맞게 다시 써라.

[규칙]
- 1~3문장, 공백 포함 120~200자. 통신사 데스크 톤 — 명사형·음슴체 종결.
- 해설·전망성 술어는 전 활용형 금지: '풀이되-', '해석되-', '기대되-', '예상되-',
  '평가되-', '전망되-', '~것으로 보임/보인다', '~ 주목', '~ 관심사'.
  해당 표현은 삭제하거나, 발화 주체가 명시된 인용으로만 전환할 것.
- 결측 표기('미상', '미정', '미확인', '알려지지 않음', '확인되지 않음') 금지 —
  정보가 없다는 절은 통째로 삭제하고 확인된 사실만 남길 것.
  단, 인명(김미정 등)·'의미상' 같은 정상 어휘면 그대로 둘 것.
- 원문에 없는 사실·수치 추가 금지. 길이 초과분은 해설·부차 정보 삭제로 해결.
- 큰따옴표(") 사용 금지.

[위반 항목]
{items}

JSON 배열만 출력: [{{"i": 항목번호, "text": "수정문"}}]"""


def _enforce_density(text: str, client, system_prompt: str) -> str:
    """해설 술어·200자 초과 ▪ 항목만 골라 1회 재작성 요청 후 치환.

    어떤 실패도 발행을 막지 않음 — 예외·파싱 실패·줄 불일치 시 원문 반환.
    """
    try:
        lines = text.split("\n")
        bad = []  # (줄번호, 본문)
        for i, line in enumerate(lines):
            s = line.strip()
            if not s.startswith("▪"):
                continue
            body = s.lstrip("▪").strip()
            if BANNED_PREDICATE_RE.search(body) or len(body) > MAX_ITEM_CHARS:
                bad.append((i, body))
        if not bad:
            return text
        logger.warning(f"[문체강제] 위반 항목 {len(bad)}건 재작성 요청 "
                       f"(해설 술어/{MAX_ITEM_CHARS}자 초과)")
        listing = "\n".join(f"{n}. {b}" for n, (_, b) in enumerate(bad, 1))
        kwargs = {"system": system_prompt} if system_prompt else {}
        resp = client.messages.create(
            model=HAIKU_MODEL, max_tokens=3000,
            messages=[{"role": "user",
                       "content": REWRITE_PROMPT.format(items=listing)}],
            **kwargs)
        raw = resp.content[0].text
        data = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        fixed = 0
        for entry in data:
            try:
                idx = int(entry["i"]) - 1
                new_body = (entry.get("text") or "").strip()
                if 0 <= idx < len(bad) and new_body \
                        and not BANNED_PREDICATE_RE.search(new_body):
                    lines[bad[idx][0]] = "▪ " + new_body
                    fixed += 1
            except Exception:
                continue
        logger.info(f"[문체강제] 재작성 반영 {fixed}/{len(bad)}건")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[문체강제] 실패 — 원문 유지: {e}")
        return text


def _pin_crypto_line(text: str, crypto_line: str | None) -> str:
    """시세 줄을 💰 경제/산업 섹션 마지막 줄로 결정론 이동/삽입.

    crypto_line 없으면(수집 실패 폴백) 원문 그대로.
    """
    if not crypto_line:
        return text
    try:
        lines = [ln for ln in text.split("\n") if "📈 시세" not in ln]
        econ = next((i for i, ln in enumerate(lines) if ln.strip().startswith("💰")), None)
        if econ is None:
            return text
        end = econ + 1
        while end < len(lines) and lines[end].strip():
            end += 1
        lines.insert(end, crypto_line)
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[시세고정] 실패 — 원문 유지: {e}")
        return text


def _normalize_bullet_spacing(text: str) -> str:
    """▪ 항목 사이·섹션 헤더 직후의 빈 줄을 결정론적으로 제거.

    모델이 가독성 성향으로 항목 사이에 빈 줄을 넣는 문제를 프롬프트 대신
    후처리로 보장한다. 섹션 사이 빈 줄(다음 줄이 ▪ 가 아닌 경우)은 유지.
    """
    lines = text.split("\n")
    out: list[str] = []
    for i, ln in enumerate(lines):
        if not ln.strip():
            nxt = next((l for l in lines[i + 1:] if l.strip()), "")
            prev = out[-1].strip() if out else ""
            # 다음 내용 줄이 ▪ 항목이면(=항목 사이/헤더 직후 빈 줄) 제거
            if nxt.startswith("▪") and prev:
                continue
        out.append(ln)
    return "\n".join(out)


# ══════════════════════════════════════════════════
#  4. 텔레그램 전송
# ══════════════════════════════════════════════════
def _split_text(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """텍스트를 limit 이하 청크로 분할. 줄바꿈 기준으로 자른다."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # 줄바꿈 기준으로 자를 위치 탐색
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def send_to_telegram(text: str) -> dict:
    """텔레그램 채널/그룹으로 브리핑 전송. 4096자 초과 시 분할 전송."""
    bot_token = _env("NUREONGI_NEWS_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise EnvironmentError(
            "NUREONGI_NEWS_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다."
        )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _split_text(text)
    result = None

    for i, chunk in enumerate(chunks, 1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        msg_id = result.get('result', {}).get('message_id')
        logger.info(f"텔레그램 전송 성공 ({i}/{len(chunks)}, message_id: {msg_id})")

    return result


# ══════════════════════════════════════════════════
#  5. 메인 진입점
# ══════════════════════════════════════════════════
def send_briefing():
    """
    scheduler_worker.py에서 호출하는 메인 함수.
    RSS 수집 → AI 요약 → 텔레그램 전송 전체 파이프라인.
    """
    try:
        logger.info("=" * 50)
        logger.info("AI 브리핑 파이프라인 시작")
        logger.info("=" * 50)

        # 1) 시간대 계산
        start, end, period = get_time_window()
        logger.info(f"브리핑 유형: {period}")
        logger.info(f"수집 범위 : {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%m/%d %H:%M')} KST")
        
        # 1.5) 중복 브리핑 방지 로직 적용
        from app import create_app, db
        from app.models.briefing import Briefing
        _app = create_app()
        with _app.app_context():
            btype = 'ai_morning' if '아침' in period else 'ai_evening'
            today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
            if btype == 'ai_evening':
                today_start = today_start.replace(hour=12) # 저녁 브리핑은 12시 이후
            
            existing = Briefing.query.filter(Briefing.briefing_type == btype, Briefing.created_at >= today_start).first()
            if existing:
                logger.warning(f"이미 오늘자 {period} 브리핑이 생성되어 재생성 및 중복발송을 방지합니다.")
                return

        # 2) RSS 수집
        categorized = fetch_news_by_category(start, end)
        total_raw = sum(len(v) for v in categorized.values())
        logger.info(f"RSS 수집 완료: {total_raw}건")

        # 2.5) 타임라인 필터 2차 검증 (절대 상한 체크)
        try:
            from timeline_filter import filter_articles
            btype = 'ai_morning' if '아침' in period else 'ai_evening'
            for cat in categorized:
                categorized[cat] = filter_articles(
                    categorized[cat], start, end, briefing_type=btype
                )
            total = sum(len(v) for v in categorized.values())
            if total < total_raw:
                logger.warning(f"[타임라인 필터] {total_raw}건 → {total}건 (구식 {total_raw - total}건 제거)")
        except Exception as tf_err:
            logger.error(f"[타임라인 필터] 실행 실패: {tf_err}")
            total = total_raw

        if total == 0:
            logger.warning("수집된 뉴스가 없어 브리핑을 건너뜁니다.")
            return

        # 2.7) 시세 수집 (실패해도 파이프라인 계속 — 폴백: 시세 줄 생략)
        crypto_line = fetch_crypto_prices()
        if crypto_line:
            logger.info(f"[시세] 수집 완료: {crypto_line}")
        else:
            logger.warning("[시세] Upbit 조회 실패 — 시세 줄 생략")

        # 3) AI 요약
        briefing = generate_briefing_with_ai(categorized, period, crypto_line)
        if not briefing:
            logger.warning("AI 브리핑 생성 실패 — 건너뜁니다.")
            return

        # 3.5) 팩트체크 — 발송 전 인물·직책 오류 자동 감지·수정
        try:
            from fact_checker import run_fact_check, auto_fix
            fc_result = run_fact_check(briefing)
            if not fc_result["passed"]:
                logger.warning(f"[팩트체크 오류] {fc_result['errors']}")
                briefing = auto_fix(briefing)

                # 관리자에게 수정 내역 별도 알림
                admin_msg = "⚠️ <b>AI 브리핑 팩트 자동수정</b>\n\n"
                for err in fc_result["errors"]:
                    admin_msg += f"• '{err['found']}' → '{err['should_be']}'\n"
                    admin_msg += f"  문맥: {err.get('context', '')}\n"
                try:
                    from app.utils.telegram_notify import send_to_admin
                    send_to_admin(admin_msg)
                except Exception:
                    pass
            else:
                logger.info("[팩트체크] 오류 없음 — 통과")
        except Exception as fc_err:
            logger.error(f"[팩트체크] 실행 실패 (브리핑은 그대로 발송): {fc_err}")

        # 3.7) 발행 전 자가 검증 패스 — 고위험 항목만 웹검색 교차 검증.
        #      run_verify_pass 는 내부에서 모든 예외를 삼키지만, import 실패까지
        #      포함해 어떤 경우에도 발행을 중단시키지 않도록 이중 방어.
        try:
            from verify_pass import run_verify_pass
            briefing = run_verify_pass(
                briefing, briefing_type='ai_morning' if '아침' in period else 'ai_evening')
        except Exception as vp_err:
            logger.error(f"[자가검증] 패스 실행 실패 — 스킵하고 발행: {vp_err}")

        # 4) 텔레그램 전송 (nr2.kr 유입 문구 추가)
        nr2_footer = (
            "\n\n━━━━━━━━━━━━━━━━\n"
            "📖 오늘 브리핑 전문 + 심층 토론\n"
            "👉 https://nr2.kr\n"
            "━━━━━━━━━━━━━━━━"
        )
        send_to_telegram(briefing + nr2_footer)
        # 5) DB 저장
        try:
            from app import create_app, db
            from app.models.briefing import Briefing
            _app = create_app()
            with _app.app_context():
                btype = 'ai_morning' if '아침' in period else 'ai_evening'
                first_line = briefing.split('\n')[0][:200]
                record = Briefing(
                    briefing_type=btype,
                    title=first_line,
                    content=briefing,
                    article_count=total,
                )
                db.session.add(record)
                db.session.commit()
                logger.info(f"AI 브리핑 DB 저장 완료 (id={record.id})")
                # 채널 알림
                # send_to_telegram에서 전문을 발송했으므로 notify_new_briefing은 비활성화하여 
                # 두 번째 단축된(truncated) 메시지가 중복 발송되는 버그를 방지합니다.
                # try:
                #     from app.utils.telegram_notify import notify_new_briefing
                #     notify_new_briefing(record)
                # except Exception as ne:
                #     logger.error(f"AI 브리핑 채널 알림 실패: {ne}")
        except Exception as e:
            logger.error(f"AI 브리핑 DB 저장 실패: {e}")

        logger.info("=" * 50)
        logger.info("AI 브리핑 파이프라인 완료 ✅")
        logger.info("=" * 50)

        # 6) 카드뉴스 자동 생성 — 아침 브리핑 때 1회만 실행.
        #    (전날 저녁 브리핑 + 당일 아침 브리핑을 합쳐 하루치 카드뉴스 8장 생성.
        #     이미지 생성 비용을 하루 1회로 묶기 위함)
        #    브리핑 발송과 완전히 분리 — 카드 생성이 실패해도 발송엔 영향 없음.
        if "아침" in period:
            try:
                from cardnews_daily import run_daily_cardnews_safe
                run_daily_cardnews_safe(morning_briefing=briefing)
            except Exception as cn_err:
                logger.error(f"[카드뉴스] 트리거 실패(브리핑 발송에는 영향 없음): {cn_err}")

    except Exception as e:
        logger.error(f"AI 브리핑 오류: {e}", exc_info=True)


# ── 직접 실행 (테스트용) ──────────────────────────
if __name__ == "__main__":
    send_briefing()
