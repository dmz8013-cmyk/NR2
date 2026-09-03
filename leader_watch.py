"""
leader_watch.py — AI 거두 워치 (Phase 1: 발행기 + 수동 입력 모드)

X(트위터)의 AI·지정학 거두 발언을 큐레이션해 발행하는 모듈.
기존 인프라(Postgres db_conn / Claude 채점 / verify_pass / 텔레그램 발행 /
nr2.kr 웹)를 재사용하며 새 서비스는 만들지 않는다.

흐름(수동 모드):
  /leaders_in + 붙여넣기 텍스트(그록 수집 결과)
  → 파싱(인물|시각|요약|링크, 링크 없으면 폐기)
  → 워치리스트 매칭(핸들 → 이름 → '기타')
  → Claude 채점(lens='거두', 7점 이상 통과) → 고밀도 1줄 카드(최대 12항목)
  → verify_pass 훅 → 관리자 DM 미리보기
  → /leaders_ok 발행(텔레 AESA 채널 + nr2.kr/ai-leaders/날짜 + CTA) / /leaders_no 폐기

안전: 모든 단계 이중 try/except — 발행 중단 경로 없음, 실패 시 관리자 DM.
Phase 2(xAI 자동 수집기)는 XAI_API_KEY 설정 후 별도 추가 예정.
"""

import os
import re
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:
    anthropic = None

from g2b_tracker import db_conn, state_get, state_set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("leader_watch")

KST = ZoneInfo("Asia/Seoul")
_HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(_HERE, "config", "watchlist.json")

SCORE_MODEL = "claude-sonnet-4-6"      # AESA 채점과 동일 모델
MIN_SCORE = 7
MAX_ITEMS = 12
DRAFT_STATE_KEY = "leaders_draft"
AWAIT_STATE_KEY = "leaders_await"

# CTA (환경변수 우선, 기본값은 기존 정보방 링크)
def _cta() -> str:
    kakao = os.environ.get("KAKAO_LINK", "https://buly.kr/7mBN720")
    tele = os.environ.get("TELE_LINK", "https://t.me/gazzzza2025")
    return f"누렁이 정보방(카톡) {kakao}\nAESA 텔레 {tele}"


def admin_chat_id() -> str:
    return os.environ.get("LEADERS_ADMIN_CHAT_ID",
                          os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076"))


# ══════════════════════════════════════════════════
#  1. DB
# ══════════════════════════════════════════════════
def init_leader_db() -> bool:
    conn = db_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS leader_posts (
                id          SERIAL PRIMARY KEY,
                date        DATE NOT NULL,
                handle      VARCHAR(60),
                name        VARCHAR(80),
                tier        INT,
                post_url    TEXT UNIQUE,
                summary_ko  TEXT,
                lens        VARCHAR(20) DEFAULT '거두',
                score       INT,
                bias_label  VARCHAR(10),
                published   BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT NOW()
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_leader_posts_date ON leader_posts (date)")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[거두] 스키마 생성 실패: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False


# ══════════════════════════════════════════════════
#  2. 워치리스트
# ══════════════════════════════════════════════════
_wl_cache = None


def load_watchlist() -> list[dict]:
    """ai/geo 배열 통합 목록 (handle 소문자 키 포함)."""
    global _wl_cache
    if _wl_cache is None:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _wl_cache = [{**p, "group": g} for g in ("ai", "geo") for p in data.get(g, [])]
    return _wl_cache


def match_person(token: str) -> dict | None:
    """핸들(@ 유무 무관) → 이름 순으로 워치리스트 매칭. 실패 시 None('기타')."""
    t = token.strip().lstrip("@").lower()
    if not t:
        return None
    for p in load_watchlist():
        if p["handle"].lower() == t:
            return p
    for p in load_watchlist():
        if t in p["name"].lower() or p["name"].lower() in t:
            return p
    return None


# ══════════════════════════════════════════════════
#  3. 수동 입력 파싱
# ══════════════════════════════════════════════════
URL_RE = re.compile(r"https?://\S+")


def parse_manual_input(text: str) -> tuple[list[dict], int]:
    """그록 수집 텍스트 → 항목 리스트. '인물|시각|요약|링크' 줄 단위.

    반환: (items, dropped_no_link). 링크 없는 항목은 폐기.
    """
    items, dropped = [], 0
    for raw in text.split("\n"):
        line = raw.strip().lstrip("▪-•* ").strip()
        if not line or line.startswith("/"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        url_m = URL_RE.search(line)
        if not url_m:
            dropped += 1
            continue
        url = url_m.group(0).rstrip(").,]")
        person_tok = parts[0]
        ts = parts[1] if len(parts) >= 4 else ""
        summary = (parts[2] if len(parts) >= 4 else parts[1])
        summary = URL_RE.sub("", summary).strip() or URL_RE.sub("", line).strip()

        matched = match_person(person_tok)
        items.append({
            "handle": (matched or {}).get("handle") or person_tok.lstrip("@")[:60],
            "name": (matched or {}).get("name") or person_tok.lstrip("@")[:80],
            "affil": (matched or {}).get("affil", ""),
            "tier": (matched or {}).get("tier"),
            "bias_label": (matched or {}).get("bias_label"),
            "matched": matched is not None,
            "ts": ts, "summary_raw": summary, "post_url": url,
        })
    return items, dropped


# ══════════════════════════════════════════════════
#  4. 채점 + 카드 편집
# ══════════════════════════════════════════════════
SCORE_PROMPT = """당신은 AESA(AI·지정학 큐레이션)의 편집자다. lens='거두'.
다음은 AI·지정학 거물급 인물의 X(트위터) 발언 요약이다. 파급력을 채점하고
한국 독자용 고밀도 1줄 요약을 작성하라.

인물: {name} ({affil})
발언 요약(원자료): {summary}

[채점 0~10] 산업·시장·정책·외교에 미치는 파급력. 신제품/정책 발표·중대 입장 변화 8~10,
의미 있는 발언 6~7, 일상·홍보·잡담 0~5.
[요약 규칙] 1~3문장, 공백 포함 120~200자. 통신사 데스크 톤(명사형·음슴체).
발언 내용의 사실 전달만 — 해설·전망성 술어(풀이되-/예상되- 등) 금지.
원문에 없는 수치·내용 지어내기 금지.

JSON만: {{"score": 0~10 정수, "summary_ko": "요약문"}}"""


def score_items(items: list[dict]) -> list[dict]:
    """Claude 채점 — score/summary_ko 부여. 실패 항목은 score=0(불통과)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or anthropic is None:
        logger.warning("[거두] ANTHROPIC 사용 불가 — 채점 생략(전항목 불통과)")
        return items
    client = anthropic.Anthropic(api_key=api_key, timeout=60.0)
    for it in items:
        try:
            resp = client.messages.create(
                model=SCORE_MODEL, max_tokens=400,
                messages=[{"role": "user", "content": SCORE_PROMPT.format(
                    name=it["name"], affil=it.get("affil") or "소속 미상",
                    summary=it["summary_raw"][:600])}])
            t = resp.content[0].text
            data = json.loads(t[t.find("{"):t.rfind("}") + 1])
            it["score"] = max(0, min(10, int(data.get("score", 0))))
            it["summary_ko"] = (data.get("summary_ko") or "").strip()[:400]
        except Exception as e:
            it["score"] = 0
            it["summary_ko"] = ""
            logger.warning(f"[거두] 채점 실패 스킵({it['handle']}): {e}")
    return items


def build_card(items: list[dict], date_str: str) -> str:
    """통과 항목 → 고밀도 1줄 카드. 원문 재게시 금지: 요약+링크만."""
    lines = [f"🎙️ AI 거두 워치 | {date_str}", ""]
    for it in items:
        prefix = f"[{it['bias_label']}] " if it.get("bias_label") else ""
        who = it["name"] + (f"({it['affil']})" if it.get("affil") else "")
        lines.append(f"▪ {prefix}{who}: {it['summary_ko']} {it['post_url']}")
    lines += ["", _cta()]
    return "\n".join(lines)


# ══════════════════════════════════════════════════
#  5. 파이프라인 (수동 입력 → 미리보기 초안)
# ══════════════════════════════════════════════════
def _send_admin(text: str) -> None:
    try:
        from app.utils.telegram_notify import send_telegram_message
        send_telegram_message(text, chat_id=admin_chat_id())
    except Exception:
        # 앱 컨텍스트 밖(드라이런 등) — 직접 전송 폴백
        try:
            import requests
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if token:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": admin_chat_id(), "text": text,
                                    "parse_mode": "HTML",
                                    "disable_web_page_preview": True}, timeout=20)
        except Exception as e:
            logger.warning(f"[거두] 관리자 DM 실패(무시): {e}")


def process_manual_input(text: str) -> str:
    """입력 텍스트 → 초안 생성 + 관리자 미리보기. 상태 회신 문자열 반환."""
    try:
        init_leader_db()
        items, dropped = parse_manual_input(text)
        if not items:
            return "⚠️ 파싱된 항목이 없습니다. '인물|시각|요약|링크' 줄 형식을 확인하세요."

        # post_url 중복(이미 적재) 제거
        fresh = []
        conn = db_conn()
        if conn:
            try:
                cur = conn.cursor()
                for it in items:
                    cur.execute("SELECT 1 FROM leader_posts WHERE post_url=%s", (it["post_url"],))
                    if cur.fetchone():
                        continue
                    fresh.append(it)
                conn.close()
            except Exception:
                fresh = items
        else:
            fresh = items

        scored = score_items(fresh)
        passed = sorted([i for i in scored if i.get("score", 0) >= MIN_SCORE],
                        key=lambda x: -x["score"])[:MAX_ITEMS]
        if not passed:
            return (f"⚠️ 통과 항목 0건 (입력 {len(items)}·신규 {len(fresh)}·"
                    f"링크없음 폐기 {dropped}). {MIN_SCORE}점 미만은 발행하지 않습니다.")

        today = datetime.now(KST).strftime("%Y-%m-%d")
        card = build_card(passed, datetime.now(KST).strftime("%m/%d"))

        # verify_pass 훅 (제품명·수치·직함 웹검색 대조) — 실패해도 초안 유지
        try:
            from verify_pass import run_verify_pass
            card = run_verify_pass(card, briefing_type="leader_watch")
        except Exception as ve:
            logger.warning(f"[거두] verify_pass 스킵: {ve}")

        # 초안 저장 (발행 대기)
        state_set(DRAFT_STATE_KEY, json.dumps(
            {"date": today, "card": card, "items": passed}, ensure_ascii=False))

        unmatched = sum(1 for i in passed if not i.get("matched"))
        _send_admin("🔍 <b>[미리보기] AI 거두 워치</b>\n"
                    f"(입력 {len(items)} → 신규 {len(fresh)} → 통과 {len(passed)}"
                    f"{f' · 기타 {unmatched}' if unmatched else ''}"
                    f"{f' · 링크없음 폐기 {dropped}' if dropped else ''})\n"
                    "승인: /leaders_ok · 폐기: /leaders_no\n\n" + card)
        return f"✅ 초안 생성 — 통과 {len(passed)}건. 미리보기 DM 확인 후 /leaders_ok 또는 /leaders_no"
    except Exception as e:
        logger.error(f"[거두] 입력 처리 실패: {e}", exc_info=True)
        _send_admin(f"❌ <b>거두 워치 입력 처리 실패</b>\n{str(e)[:300]}")
        return f"❌ 처리 실패: {e}"


# ══════════════════════════════════════════════════
#  6. 발행 / 폐기
# ══════════════════════════════════════════════════
def publish_draft() -> str:
    """/leaders_ok — 텔레 채널 + DB(웹 페이지용) 동시 발행."""
    try:
        raw = state_get(DRAFT_STATE_KEY)
        if not raw or raw == "null":
            return "⚠️ 발행 대기 중인 초안이 없습니다."
        draft = json.loads(raw)
        card, items, date = draft["card"], draft["items"], draft["date"]

        # (b) DB 적재 → nr2.kr/ai-leaders/<date> 페이지가 즉시 서빙
        saved = 0
        conn = db_conn()
        if conn:
            try:
                cur = conn.cursor()
                for it in items:
                    cur.execute("""
                        INSERT INTO leader_posts
                          (date, handle, name, tier, post_url, summary_ko, lens,
                           score, bias_label, published)
                        VALUES (%s,%s,%s,%s,%s,%s,'거두',%s,%s,TRUE)
                        ON CONFLICT (post_url) DO UPDATE SET published=TRUE
                    """, (date, it["handle"], it["name"], it.get("tier"),
                          it["post_url"], it["summary_ko"], it["score"],
                          it.get("bias_label")))
                    saved += 1
                conn.commit()
                conn.close()
            except Exception as de:
                logger.error(f"[거두] DB 적재 실패: {de}")

        # (a) 텔레 AESA 채널 (기존 발행 경로 재사용)
        sent = False
        try:
            from ai_briefing import _split_text
            import requests
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            channel = os.environ.get("AESA_TELEGRAM_CHANNEL_ID",
                                     os.environ.get("TELEGRAM_CHAT_ID"))
            if token and channel:
                for chunk in _split_text(card, limit=4000):
                    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                      json={"chat_id": channel, "text": chunk,
                                            "disable_web_page_preview": True}, timeout=30)
                    sent = sent or r.ok
        except Exception as te:
            logger.error(f"[거두] 채널 발행 실패: {te}")

        state_set(DRAFT_STATE_KEY, "null")
        url = f"https://nr2.kr/ai-leaders/{date}"
        result = (f"✅ 발행 완료 — DB {saved}건 / 채널 {'성공' if sent else '실패 ⚠️'}\n{url}")
        if not sent:
            _send_admin(f"⚠️ <b>거두 워치 채널 발행 실패</b> — 웹 페이지({url})는 정상. "
                        "AESA_TELEGRAM_CHANNEL_ID 확인 필요.")
        return result
    except Exception as e:
        logger.error(f"[거두] 발행 실패: {e}", exc_info=True)
        _send_admin(f"❌ <b>거두 워치 발행 실패</b>\n{str(e)[:300]}")
        return f"❌ 발행 실패: {e}"


def discard_draft() -> str:
    """/leaders_no — 초안 폐기."""
    state_set(DRAFT_STATE_KEY, "null")
    return "🗑 초안 폐기 완료."


if __name__ == "__main__":
    # 파싱·매칭 단위 테스트 (API/DB 불필요)
    sample = """@sama | 2h | GPT-6 출시 발표, 추론 비용 80% 절감 주장 | https://x.com/sama/status/111
후시진 | 5h | 대만 반도체 봉쇄 시 미국 책임론 주장 | https://x.com/HuXijin_GT/status/222
무명씨 | 1h | 링크 없는 항목 테스트
John Doe | 3h | 워치리스트 밖 인물 발언 | https://x.com/johndoe/status/333"""
    items, dropped = parse_manual_input(sample)
    for it in items:
        print(f"{'✓' if it['matched'] else '기타'} {it['name']} [{it.get('bias_label') or '-'}] {it['post_url']}")
    print(f"폐기(링크없음): {dropped}")
