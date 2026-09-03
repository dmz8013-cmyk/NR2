"""
leader_watch.py — 누렁이 시그널 (발행기 + 수동 입력 모드)

'누렁이 시그널 — 세계를 움직이는 150인의 오늘':
X(트위터)의 AI·지정학 거물 150인 발언을 큐레이션해 발행하는 모듈.
기존 인프라(Postgres db_conn / Claude 채점 / verify_pass / 텔레그램 발행 /
nr2.kr 웹)를 재사용하며 새 서비스는 만들지 않는다.

출력 채널 2종:
  · 텍스트 버전(텔레 AESA 채널·카톡 복사용) — 항목별 원문 링크 없음,
    마크다운·괄호 링크 금지, 이모지는 헤더 📡 하나만
  · 웹 버전(nr2.kr/signal/YYYY-MM-DD) — 동일 본문 + 항목별 원문 X 링크 병기

편집 규칙: X status 링크 없는 항목 폐기 → 채점(7점 컷) → 동일 이벤트
클러스터링(클러스터당 최대 2, 나머지는 웹 '관련 링크') → 총 5~8개
→ verify_pass(항목 단위, 링크와 분리 검증) → 관리자 DM 미리보기(텍스트 버전)
→ /leaders_ok 발행(채널 텍스트 + 웹 DB 동시) / /leaders_no 폐기

안전: 모든 단계 이중 try/except — 발행 중단 경로 없음, 실패 시 관리자 DM.
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
MAX_ITEMS = 8                          # 텍스트 버전 총 5~8개 — 채우기용 중복 금지
DRAFT_STATE_KEY = "leaders_draft"
AWAIT_STATE_KEY = "leaders_await"

PRODUCT_NAME = "누렁이 시그널"
TAGLINE = "세계를 움직이는 150인의 오늘"
SEP = "━" * 16
WEB_BASE = "nr2.kr/signal"

# 원문 링크 강제: 실제 X status 링크만 인정 (모델이 지어낸 자리표시자
# 'https://x.com/...' 류 차단)
STATUS_URL_RE = re.compile(r"https?://(?:x|twitter)\.com/[A-Za-z0-9_]{1,20}/status/\d{5,}")


def valid_post_url(url: str) -> bool:
    return bool(url and STATUS_URL_RE.match(url.strip()))


def _cta_lines() -> list[str]:
    kakao = os.environ.get("KAKAO_LINK", "https://buly.kr/7mBN720")
    tele = os.environ.get("TELE_LINK", "https://t.me/gazzzza2025")
    return [f"누렁이 정보방(카카오톡) {kakao}", f"누렁이 정보방(텔레그램) {tele}"]


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
        # Phase 2 수집기용: 원문 보관(요약과 분리) + 파급 지표(월간 리포트 근거)
        cur.execute("ALTER TABLE leader_posts ADD COLUMN IF NOT EXISTS raw_text TEXT")
        cur.execute("ALTER TABLE leader_posts ADD COLUMN IF NOT EXISTS metrics_json TEXT")
        # 클러스터 초과분: 텍스트 버전 제외, 웹 '관련 링크'로만 노출
        cur.execute("ALTER TABLE leader_posts ADD COLUMN IF NOT EXISTS related BOOLEAN DEFAULT FALSE")
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
    """ai/geo 배열 통합 목록 (v2026-09 스키마 정규화).

    - 소속 키: v2026-09는 'org', 구버전은 'affil' → affil 로 통일
    - 편향 라벨: 최상위 bias_label 핸들 목록 기준 부여
      (org 가 관영·조직·매체면 [관영], 개인이면 [편향])
    - candidates(후보 풀)·aux·cn_pipe 는 활성 150에 미포함
    """
    global _wl_cache
    if _wl_cache is None:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        bias_handles = {h.lower() for h in data.get("bias_label", [])}
        out = []
        for g in ("ai", "geo"):
            for p in data.get(g, []):
                e = dict(p)
                e["group"] = g
                e["affil"] = e.get("org") or e.get("affil") or ""
                if e.get("handle", "").lower() in bias_handles:
                    org = e["affil"]
                    e["bias_label"] = "관영" if any(k in org for k in ("관영", "조직", "매체")) else "편향"
                else:
                    e.setdefault("bias_label", None)
                out.append(e)
        _wl_cache = out
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
SCORE_PROMPT = """당신은 '누렁이 시그널'(AI·지정학 큐레이션)의 편집자다.
다음은 AI·지정학 거물급 인물의 X(트위터) 발언이다. 파급력을 채점하고
한국 독자용 본문을 작성하라.

인물: {name} ({affil})
발언(원자료): {summary}
{fact_names}
[채점 0~10] 산업·시장·정책·외교에 미치는 파급력. 신제품/정책 발표·중대 입장 변화 8~10,
의미 있는 발언 6~7, 일상·홍보·잡담 0~5.
[본문 규칙 — 전부 준수]
- 1~3문장, 공백 포함 120~200자. 통신사 데스크 톤(명사형·음슴체).
- 본문에서 인물명({name}) 반복 금지 — 인물명은 카드 머리에 별도 표기됨.
- 발언 내용의 사실 전달만 — 해설·전망성 술어(풀이되-/예상되-/평가되- 등) 금지.
- 원문에 없는 수치·내용 지어내기 금지. 미확인 전언은 "~로 전해짐" 완곡체,
  '[확인 중]' 같은 태그 금지.
- 2차 출처 인용이면 원출처 명시 (예: "알아라비야 보도, 익명 미 소식통 인용").
- 인명 한글 표기는 위 표준 표기를 우선, 제품명·모델명은 원문 표기 그대로.
- 마크다운·괄호 링크·URL·이모지 금지 (순수 문장만).
[핵심어] 동일 이벤트 판별용 — 이 발언의 제품명·인명·지명·기관명 2~5개
(원문 표기, 일반명사 금지).

JSON만: {{"score": 0~10 정수, "summary_ko": "본문", "keywords": ["핵심어", ...]}}"""


_fact_names_cache = None


def _fact_names_block() -> str:
    """config/facts.json 인물_직함 → 인명 표준 표기 블록 (없으면 빈 문자열)."""
    global _fact_names_cache
    if _fact_names_cache is None:
        try:
            with open(os.path.join(_HERE, "config", "facts.json"), encoding="utf-8") as f:
                names = json.load(f).get("인물_직함", {})
            _fact_names_cache = ("[인명 표준 표기] " +
                                 ", ".join(f"{k}={v}" for k, v in names.items()) + "\n") \
                if names else ""
        except Exception:
            _fact_names_cache = ""
    return _fact_names_cache


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
                model=SCORE_MODEL, max_tokens=500,
                messages=[{"role": "user", "content": SCORE_PROMPT.format(
                    name=it["name"], affil=it.get("affil") or "소속 미상",
                    summary=it["summary_raw"][:600],
                    fact_names=_fact_names_block())}])
            t = resp.content[0].text
            data = json.loads(t[t.find("{"):t.rfind("}") + 1])
            it["score"] = max(0, min(10, int(data.get("score", 0))))
            it["summary_ko"] = (data.get("summary_ko") or "").strip()[:400]
            it["keywords"] = [str(k).strip().lower()
                              for k in (data.get("keywords") or []) if str(k).strip()][:5]
        except Exception as e:
            it["score"] = 0
            it["summary_ko"] = ""
            logger.warning(f"[거두] 채점 실패 스킵({it['handle']}): {e}")
    return items


def _who_prefix(it: dict) -> str:
    """항목 머리 — 라벨 계정은 '[관영] 신화통신', 그 외 '인물명(직함)'."""
    if it.get("bias_label"):
        return f"[{it['bias_label']}] {it['name']}"
    affil = (it.get("affil") or "").strip()
    if not affil:
        return it["name"]
    if affil == "조직":
        return f"{it['name']}(조직)"
    if "매체" in affil or "언론" in affil:
        return f"{it['name']}(매체)"
    return f"{it['name']}({affil})"


def cluster_items(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """동일 이벤트 클러스터링 — 편집창(24h) 내 핵심어(제품명·인명·지명) 겹침 = 1클러스터.

    클러스터당 최대 2개(파급 최고 1 + 다른 인물의 시각 1), 나머지는 웹 '관련 링크'.
    총 본문 MAX_ITEMS(8)개 — 채우기 위한 중복 없음, 5개면 5개.
    반환: (main, related) — 둘 다 파급순.
    """
    items = sorted(items, key=lambda x: -x.get("score", 0))
    n = len(items)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    kws = [set(it.get("keywords") or []) for it in items]
    for i in range(n):
        for j in range(i + 1, n):
            if kws[i] & kws[j]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    main, related = [], []
    for idxs in clusters.values():          # idxs는 파급순 유지
        picked = {idxs[0]}
        top_handle = (items[idxs[0]].get("handle") or "").lower()
        for j in idxs[1:]:
            if (items[j].get("handle") or "").lower() != top_handle:
                picked.add(j)
                break
        for j in idxs:
            (main if j in picked else related).append(items[j])

    main = sorted(main, key=lambda x: -x.get("score", 0))
    if len(main) > MAX_ITEMS:
        related = main[MAX_ITEMS:] + related
        main = main[:MAX_ITEMS]
    return main, sorted(related, key=lambda x: -x.get("score", 0))


def build_text_card(items: list[dict], date_iso: str) -> str:
    """텍스트 버전(텔레 채널·카톡 복사용) — 항목별 링크 없음, 이모지는 📡 하나.

    마크다운·괄호 링크 문법 금지: URL은 순수 문자열로만 포함.
    """
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    lines = [f"📡 {PRODUCT_NAME} | {dt.month:02d}/{dt.day:02d}", TAGLINE, ""]
    lines += _cta_lines()
    lines += ["", SEP, ""]
    for it in items:
        lines.append(f"▪ {_who_prefix(it)}: {it['summary_ko']}")
    lines += ["", SEP, ""]
    lines.append(f"원문 링크·전체 보기 → {WEB_BASE}/{date_iso}")
    lines += _cta_lines()
    return "\n".join(lines)


def _verify_items(items: list[dict]) -> None:
    """verify_pass를 항목 본문에만 적용 — 링크·머리 표기와 분리해 URL 유실 원천 차단.

    (기존에는 카드 전문을 넘겨 수정문 교체 시 줄 끝 URL이 함께 사라졌음.)
    확인불가 항목은 완곡체 교체만 반영, ⚠️ 이모지는 제거(텍스트 버전 이모지 규칙).
    """
    try:
        from verify_pass import run_verify_pass
        pseudo = "\n".join("▪ " + (it.get("summary_ko") or "") for it in items)
        out = run_verify_pass(pseudo, briefing_type="leader_watch")
        new = [ln.strip() for ln in out.split("\n") if ln.strip().startswith("▪")]
        if len(new) != len(items):
            logger.warning(f"[시그널] verify 결과 줄 수 불일치({len(new)}≠{len(items)}) — 원문 유지")
            return
        for it, line in zip(items, new):
            body = line.lstrip("▪").strip().lstrip("⚠️").strip()
            if body:
                it["summary_ko"] = body
    except Exception as ve:
        logger.warning(f"[시그널] verify_pass 스킵: {ve}")


def finalize_and_preview(scored: list[dict], meta_lines: list[str]) -> str:
    """채점 완료 항목 → 링크 강제 → 점수 컷 → 클러스터 → verify → 텍스트 카드
    → 초안 저장 + 관리자 미리보기(텍스트 버전). 상태 문자열 반환."""
    linked = [i for i in scored if valid_post_url(i.get("post_url", ""))]
    dropped_link = len(scored) - len(linked)
    if dropped_link:
        logger.warning(f"[시그널] 링크 무효 폐기 {dropped_link}건")
    passed = [i for i in linked if i.get("score", 0) >= MIN_SCORE]
    if not passed:
        return (f"⚠️ 통과 항목 0건 (채점 {len(scored)}"
                f"{f'·링크무효 폐기 {dropped_link}' if dropped_link else ''}). "
                f"{MIN_SCORE}점 미만은 발행하지 않습니다.")

    main, related = cluster_items(passed)
    _verify_items(main)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    card = build_text_card(main, today)
    state_set(DRAFT_STATE_KEY, json.dumps(
        {"date": today, "card": card, "items": main, "related": related},
        ensure_ascii=False))

    meta = " · ".join(x for x in [
        f"본문 {len(main)}", f"관련 링크 {len(related)}" if related else "",
        f"링크무효 폐기 {dropped_link}" if dropped_link else ""] if x)
    _send_admin("🔍 <b>[미리보기] 누렁이 시그널</b>\n"
                + "\n".join(meta_lines + [f"({meta})"])
                + "\n승인: /leaders_ok · 폐기: /leaders_no\n\n" + card)
    return (f"✅ 초안 생성 — 본문 {len(main)}건·관련 {len(related)}건. "
            "미리보기 DM 확인 후 /leaders_ok 또는 /leaders_no")


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
        return finalize_and_preview(
            scored, [f"(입력 {len(items)} → 신규 {len(fresh)}"
                     f"{f' · 링크없음 폐기 {dropped}' if dropped else ''})"])
    except Exception as e:
        logger.error(f"[시그널] 입력 처리 실패: {e}", exc_info=True)
        _send_admin(f"❌ <b>누렁이 시그널 입력 처리 실패</b>\n{str(e)[:300]}")
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
        related = draft.get("related") or []

        # (b) DB 적재 → nr2.kr/signal/<date> 웹 버전이 즉시 서빙
        #     (본문 related=FALSE, 클러스터 초과분 related=TRUE — 웹 '관련 링크')
        saved = 0
        conn = db_conn()
        if conn:
            try:
                cur = conn.cursor()
                for it, is_rel in [(i, False) for i in items] + [(i, True) for i in related]:
                    cur.execute("""
                        INSERT INTO leader_posts
                          (date, handle, name, tier, post_url, summary_ko, lens,
                           score, bias_label, published, related)
                        VALUES (%s,%s,%s,%s,%s,%s,'거두',%s,%s,TRUE,%s)
                        ON CONFLICT (post_url) DO UPDATE
                          SET published=TRUE, related=EXCLUDED.related,
                              summary_ko=EXCLUDED.summary_ko, score=EXCLUDED.score,
                              date=EXCLUDED.date
                    """, (date, it["handle"], it["name"], it.get("tier"),
                          it["post_url"], it.get("summary_ko", ""), it.get("score"),
                          it.get("bias_label"), is_rel))
                    saved += 1
                conn.commit()
                conn.close()
            except Exception as de:
                logger.error(f"[시그널] DB 적재 실패: {de}")

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
            logger.error(f"[시그널] 채널 발행 실패: {te}")

        state_set(DRAFT_STATE_KEY, "null")
        url = f"https://{WEB_BASE}/{date}"
        result = (f"✅ 발행 완료 — DB {saved}건 / 채널 {'성공' if sent else '실패 ⚠️'}\n{url}")
        if not sent:
            _send_admin(f"⚠️ <b>누렁이 시그널 채널 발행 실패</b> — 웹 페이지({url})는 정상. "
                        "AESA_TELEGRAM_CHANNEL_ID 확인 필요.")
        return result
    except Exception as e:
        logger.error(f"[시그널] 발행 실패: {e}", exc_info=True)
        _send_admin(f"❌ <b>누렁이 시그널 발행 실패</b>\n{str(e)[:300]}")
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
