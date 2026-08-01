"""
cardnews.py — 누렁이 AESA 카드뉴스 자동 생성 모듈 (v1.0)

매일 브리핑 텍스트를 입력받아 1080×1080 PNG 카드 8장을 자동 생성한다.
  1장   : 표지 — 오늘 날짜 + 헤드라인 1줄 + 누렁이 로고
  2~7장 : 핵심 이슈 6개 — Claude API로 브리핑 전체 항목의 중요도를 평가해
          상위 6개 선별(파급력·시의성·독자 관심). 카드당 제목 + 음슴체 요약 + 섹션 라벨
  8장   : 엔딩 — "매일 아침, AI가 세계를 스캔합니다" + 정보방 링크 + 로고

렌더링: HTML/CSS 템플릿 1개 → Playwright(headless chromium) 스크린샷.
전송  : 텔레그램 sendMediaGroup 으로 관리자 채팅에만 (공개방 자동발송 안 함).

호출:
  - ai_briefing.send_briefing() 말미에서 run_cardnews_safe(briefing_text, period)
    (브리핑 발송과 완전히 분리 — 카드 생성 실패해도 브리핑엔 영향 없음)
  - nr2_web_bot.poll_commands() 의 /cardnews 수동 트리거

브리핑 발송 로직(ai_briefing.py)과 독립적으로 동작한다.
"""

import os
import re
import json
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:  # 배포 환경 외
    anthropic = None

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cardnews")

# ── 상수 ──────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
SELECT_MODEL = "claude-sonnet-4-6"          # AESA 봇과 동일 모델
CARD_W = CARD_H = 1080
NUM_ISSUES = 6                              # 2~7장
INFO_ROOM_LINK = "https://www.youtube.com/@NR2AESA"

# 디자인 팔레트
NAVY = "#0F1B2D"
GOLD = "#F5B301"

# 로고 후보 (우선순위 순). 첫 존재 파일을 워터마크로 사용.
_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_CANDIDATES = [
    os.path.join(_HERE, "assets", "logo.png"),                     # 사용자가 추가 예정
    os.path.join(_HERE, "app", "static", "images", "nureongi.jpg"),  # 폴백
]

# 섹션 라벨별 포인트 색 (골드 기본, 구분용 보조색)
SECTION_COLORS = {
    "정치": "#E24A5B",
    "경제": "#3FA796",
    "AI": "#5B8DEF",
    "기타": "#B08CE0",
}


# ══════════════════════════════════════════════════
#  1. Claude 로 상위 6개 이슈 선별
# ══════════════════════════════════════════════════
SELECT_PROMPT = """당신은 누렁이 AESA 카드뉴스 편집자입니다.
아래 '오늘의 브리핑 전문'에서 다뤄진 모든 이슈를 검토해, 카드뉴스로 만들
핵심 이슈 정확히 {n}개를 중요도 순으로 선별하세요.

[선별 기준]
- 파급력: 한국 정치·경제·사회에 미치는 영향의 크기
- 시의성: 오늘 시점에서의 뉴스 가치
- 독자 관심: 정보공유방 구독자가 궁금해할 만한 정도

[각 이슈 작성 규칙]
- title: 한 줄 제목 (25자 이내, 이모지·따옴표 없이)
- summary: 음슴체(~했음, ~라고 밝혔음 등 '-음/-슴' 종결) 2~3문장 요약.
  브리핑에 명시된 사실만 사용. 없는 수치·발언·감정 지어내기 금지. 각 문장 끝 완결.
- section: 정치 / 경제 / AI / 기타 중 하나 (브리핑 4개 분야에 대응)

[표지 헤드라인]
- headline: 오늘 전체를 아우르는 표지용 한 줄 헤드라인 (20자 이내, 이모지 없이)

결과물은 오직 아래 JSON 포맷으로만 반환하세요. 설명·마크다운 금지:
{{
  "headline": "표지 헤드라인 한 줄",
  "issues": [
    {{"section": "정치", "title": "제목", "summary": "음슴체 요약 2~3줄"}}
  ]
}}
issues 배열은 정확히 {n}개여야 합니다.

[오늘의 브리핑 전문]
{briefing}
"""


def _extract_json(text: str) -> dict:
    """Claude 응답에서 첫 JSON 오브젝트를 관대하게 파싱."""
    text = text.strip()
    # 코드펜스 제거
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON 오브젝트를 찾지 못함")
    return json.loads(text[start:end + 1])


def select_top_issues(briefing_text: str, n: int = NUM_ISSUES) -> dict:
    """브리핑 전문 → Claude 로 상위 n개 이슈 + 표지 헤드라인 선별.

    반환: {"headline": str, "issues": [{"section","title","summary"}, ...]}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if anthropic is None:
        raise ImportError("anthropic 패키지가 설치되지 않았습니다.")

    client = anthropic.Anthropic(api_key=api_key, timeout=40.0)
    response = client.messages.create(
        model=SELECT_MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": SELECT_PROMPT.format(n=n, briefing=briefing_text),
        }],
    )
    raw = response.content[0].text
    data = _extract_json(raw)

    headline = (data.get("headline") or "오늘의 브리핑").strip()
    issues = data.get("issues") or []

    # 정확히 n개로 정규화 (부족하면 그대로, 초과하면 상위 n개)
    norm = []
    for it in issues[:n]:
        section = (it.get("section") or "기타").strip()
        # 섹션 정규화
        if "정치" in section:
            section = "정치"
        elif "경제" in section or "산업" in section:
            section = "경제"
        elif "AI" in section or "기술" in section:
            section = "AI"
        else:
            section = "기타"
        norm.append({
            "section": section,
            "title": (it.get("title") or "").strip(),
            "summary": (it.get("summary") or "").strip(),
        })
    if not norm:
        raise ValueError("선별된 이슈가 없습니다.")

    logger.info(f"[카드뉴스] 이슈 선별 완료 — {len(norm)}개 (headline={headline})")
    return {"headline": headline, "issues": norm}


# ══════════════════════════════════════════════════
#  2. HTML 템플릿 (카드 8장)
# ══════════════════════════════════════════════════
def _logo_data_uri() -> str | None:
    """로고 파일을 data URI 로 인라인. 없으면 None(워터마크 생략)."""
    for path in LOGO_CANDIDATES:
        if os.path.exists(path):
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            mime = "png" if ext == "png" else "jpeg"
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            logger.info(f"[카드뉴스] 로고 사용: {os.path.relpath(path, _HERE)}")
            return f"data:image/{mime};base64,{b64}"
    logger.warning("[카드뉴스] 로고 파일을 찾지 못함 — 워터마크 생략")
    return None


def _esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_html(headline: str, issues: list[dict], date_str: str,
               period_label: str) -> str:
    """카드 8장을 담은 단일 HTML 문서 생성."""
    logo = _logo_data_uri()
    watermark = (
        f'<img class="logo" src="{logo}" alt="">' if logo else ""
    )

    # 1장 표지
    cards = [f"""
    <section class="card cover">
      <div class="cover-brand">누렁이 AESA</div>
      <div class="cover-date">{_esc(date_str)} · {_esc(period_label)}</div>
      <h1 class="cover-headline">{_esc(headline)}</h1>
      <div class="cover-tag">AI가 스캔한 오늘의 세계</div>
      {watermark}
    </section>"""]

    # 2~7장 이슈
    for i, it in enumerate(issues, start=1):
        sec = it["section"]
        color = SECTION_COLORS.get(sec, GOLD)
        cards.append(f"""
    <section class="card issue">
      <div class="issue-top">
        <span class="issue-no">{i:02d}</span>
        <span class="issue-label" style="background:{color}">{_esc(sec)}</span>
      </div>
      <h2 class="issue-title fit">{_esc(it['title'])}</h2>
      <p class="issue-summary fit">{_esc(it['summary'])}</p>
      {watermark}
    </section>""")

    # 8장 엔딩
    cards.append(f"""
    <section class="card ending">
      <div class="ending-mark">🐕</div>
      <h2 class="ending-copy">매일 아침,<br>AI가 세계를 스캔합니다</h2>
      <div class="ending-link">{_esc(INFO_ROOM_LINK)}</div>
      <div class="ending-brand">누렁이 AESA · 이상한 나라의 누렁이</div>
      {watermark}
    </section>""")

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ background:{NAVY}; }}
  body {{
    font-family:'Pretendard','Pretendard Variable',-apple-system,sans-serif;
    color:#fff; -webkit-font-smoothing:antialiased;
  }}
  .card {{
    position:relative;
    width:{CARD_W}px; height:{CARD_H}px;
    background:{NAVY};
    padding:96px 88px;
    display:flex; flex-direction:column;
    overflow:hidden;
  }}
  /* 상단 골드 라인 */
  .card::before {{
    content:""; position:absolute; top:0; left:0;
    width:100%; height:14px; background:{GOLD};
  }}
  .logo {{
    position:absolute; right:56px; bottom:52px;
    width:120px; height:120px; object-fit:contain;
    border-radius:24px; opacity:.92;
  }}

  /* ── 표지 ── */
  .cover {{ justify-content:center; }}
  .cover-brand {{
    font-size:40px; font-weight:800; color:{GOLD};
    letter-spacing:2px; margin-bottom:28px;
  }}
  .cover-date {{ font-size:36px; font-weight:600; color:#9fb2c8; margin-bottom:40px; }}
  .cover-headline {{
    font-size:96px; font-weight:900; line-height:1.18;
    letter-spacing:-1px; word-break:keep-all;
  }}
  .cover-tag {{
    margin-top:44px; font-size:34px; font-weight:600; color:{GOLD};
  }}

  /* ── 이슈 ── */
  .issue-top {{ display:flex; align-items:center; gap:28px; margin-bottom:44px; }}
  .issue-no {{ font-size:88px; font-weight:900; color:{GOLD}; line-height:1; }}
  .issue-label {{
    font-size:34px; font-weight:800; color:#0F1B2D;
    padding:12px 28px; border-radius:999px;
  }}
  .issue-title {{
    font-size:76px; font-weight:900; line-height:1.22;
    letter-spacing:-1px; word-break:keep-all; margin-bottom:40px;
  }}
  .issue-summary {{
    font-size:48px; font-weight:500; line-height:1.6;
    color:#d7e2ef; word-break:keep-all; flex:1;
  }}

  /* ── 엔딩 ── */
  .ending {{ justify-content:center; align-items:flex-start; }}
  .ending-mark {{ font-size:120px; margin-bottom:24px; }}
  .ending-copy {{
    font-size:84px; font-weight:900; line-height:1.28;
    letter-spacing:-1px; margin-bottom:56px; word-break:keep-all;
  }}
  .ending-link {{
    font-size:44px; font-weight:800; color:{GOLD};
    padding:18px 0; border-top:3px solid rgba(245,179,1,.4);
    border-bottom:3px solid rgba(245,179,1,.4);
  }}
  .ending-brand {{ margin-top:40px; font-size:32px; font-weight:600; color:#9fb2c8; }}
</style>
</head>
<body>
{''.join(cards)}
<script>
  // 텍스트 오버플로 자동 축소: .fit 요소가 부모(.card) 안에 담기도록 폰트 축소
  function fitAll() {{
    document.querySelectorAll('.card').forEach(function(card) {{
      card.querySelectorAll('.fit').forEach(function(el) {{
        var size = parseFloat(getComputedStyle(el).fontSize);
        var guard = 0;
        // 카드 내부 콘텐츠가 세로로 넘치면 폰트 단계적 축소
        while (card.scrollHeight > card.clientHeight && size > 20 && guard < 80) {{
          size -= 2;
          el.style.fontSize = size + 'px';
          guard++;
        }}
      }});
    }});
  }}
  window.__fitDone = false;
  (async function() {{
    try {{ if (document.fonts && document.fonts.ready) await document.fonts.ready; }}
    catch (e) {{}}
    fitAll();
    window.__fitDone = true;
  }})();
</script>
</body>
</html>"""
    return html


# ══════════════════════════════════════════════════
#  3. Playwright 렌더링 (headless chromium)
# ══════════════════════════════════════════════════
def render_cards(html: str, out_dir: str) -> list[str]:
    """HTML → 카드별 1080×1080 PNG. 저장 경로 목록 반환."""
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    paths: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(
            viewport={"width": CARD_W, "height": CARD_H},
            device_scale_factor=1,
        )
        # 'load'로 <link> 스타일시트 fetch까지 보장하고, 폰트 실제 로드는
        # 스크립트의 document.fonts.ready 로 대기(networkidle 은 CDN 지연 시 멈춤 위험).
        page.set_content(html, wait_until="load", timeout=15000)
        # 폰트 로드 + 오버플로 축소 완료 대기
        try:
            page.wait_for_function("window.__fitDone === true", timeout=10000)
        except Exception:
            logger.warning("[카드뉴스] fit 대기 타임아웃 — 그대로 렌더")

        cards = page.query_selector_all(".card")
        for idx, card in enumerate(cards, start=1):
            fname = f"{idx:02d}.png"
            fpath = os.path.join(out_dir, fname)
            card.screenshot(path=fpath)
            paths.append(fpath)

        browser.close()

    logger.info(f"[카드뉴스] {len(paths)}장 렌더 완료 → {out_dir}")
    return paths


# ══════════════════════════════════════════════════
#  4. 텔레그램 전송 (관리자 채팅, 앨범)
# ══════════════════════════════════════════════════
def _to_jpeg_payloads(paths: list[str]) -> list[tuple[str, bytes, str]]:
    """업로드용 (파일명, 바이트, MIME) 목록. PNG→JPEG 변환으로 용량 ~1/5 축소.

    텔레그램은 'photo'를 서버에서 JPEG로 재인코딩하므로 PNG 원본을 보내도
    화질 이득이 없다. 2026-08-02 06:04 PNG 8장(~12MB) 업로드가 write timeout으로
    실패한 원인 제거용. 변환 실패 시 해당 장만 PNG 원본으로 폴백.
    """
    payloads: list[tuple[str, bytes, str]] = []
    for path in paths:
        try:
            import io as _io
            from PIL import Image
            img = Image.open(path).convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            name = os.path.splitext(os.path.basename(path))[0] + ".jpg"
            payloads.append((name, buf.getvalue(), "image/jpeg"))
        except Exception as e:
            logger.warning(f"[카드뉴스] JPEG 변환 실패({e}) — PNG 원본 사용: {path}")
            with open(path, "rb") as f:
                payloads.append((os.path.basename(path), f.read(), "image/png"))
    return payloads


def send_cards_to_telegram(paths: list[str], chat_id: str,
                           caption: str = "") -> bool:
    """카드 묶음을 sendMediaGroup 으로 전송(최대 10장/앨범).

    JPEG 변환 + 넉넉한 타임아웃 + 3회 재시도. 실패 시 False 반환 —
    호출부는 반드시 반환값을 확인해 관리자 알림을 보낼 것.
    """
    import time

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("[카드뉴스] TELEGRAM_BOT_TOKEN 미설정 — 전송 생략")
        return False
    if not paths:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    payloads = _to_jpeg_payloads(paths)
    total_kb = sum(len(b) for _, b, _ in payloads) // 1024
    logger.info(f"[카드뉴스] 업로드 준비: {len(payloads)}장, {total_kb}KB")

    ok = True
    # 앨범당 최대 10장 — 초과 시 균등 분할 (12장 → 6+6, 10+2 방지)
    import math
    n = len(payloads)
    num_groups = max(1, math.ceil(n / 10))
    base, extra = divmod(n, num_groups)
    sizes = [base + 1] * extra + [base] * (num_groups - extra)
    boundaries = []
    pos = 0
    for s in sizes:
        boundaries.append((pos, pos + s))
        pos += s

    for chunk_start, chunk_end in boundaries:
        chunk = payloads[chunk_start:chunk_end]
        media = []
        files = {}
        for i, (name, data, mime) in enumerate(chunk):
            key = f"photo{i}"
            item = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and caption and chunk_start == 0:
                item["caption"] = caption
            media.append(item)
            files[key] = (name, data, mime)   # bytes라 재시도에도 재사용 가능

        sent = False
        for attempt in range(1, 4):
            try:
                resp = requests.post(
                    url,
                    data={"chat_id": chat_id, "media": json.dumps(media)},
                    files=files,
                    timeout=(30, 300),   # (connect, read/write)
                )
                if resp.ok:
                    logger.info(f"[카드뉴스] 텔레그램 앨범 전송 성공 ({len(chunk)}장)")
                    sent = True
                    break
                logger.error(f"[카드뉴스] 텔레그램 전송 실패({attempt}/3): {resp.text[:200]}")
            except Exception as e:
                logger.error(f"[카드뉴스] 텔레그램 전송 오류({attempt}/3): {e}")
            if attempt < 3:
                time.sleep(10 * attempt)
        ok = ok and sent
    return ok


# ══════════════════════════════════════════════════
#  5. 오케스트레이션
# ══════════════════════════════════════════════════
def _today_dir() -> tuple[str, str]:
    """output/cardnews/YYYY-MM-DD 경로와 날짜 문자열 반환."""
    now = datetime.now(KST)
    date_key = now.strftime("%Y-%m-%d")
    out_dir = os.path.join(_HERE, "output", "cardnews", date_key)
    return out_dir, now.strftime("%Y년 %m월 %d일")


def generate_cardnews(briefing_text: str, period: str = "",
                      chat_id: str | None = None) -> list[str]:
    """브리핑 텍스트 → 카드 8장 생성 → (chat_id 있으면) 텔레그램 전송.

    반환: 생성된 PNG 경로 목록. 예외는 호출부로 전파(run_cardnews_safe가 감쌈).
    """
    period_label = "아침" if "아침" in period else ("저녁" if "저녁" in period else "브리핑")

    # 1) 이슈 선별
    selected = select_top_issues(briefing_text)

    # 2) HTML 빌드
    out_dir, date_str = _today_dir()
    html = build_html(
        headline=selected["headline"],
        issues=selected["issues"],
        date_str=date_str,
        period_label=period_label,
    )

    # 3) 렌더
    paths = render_cards(html, out_dir)

    # 4) 전송 (관리자 채팅에만)
    target = chat_id or os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
    caption = f"🗞️ 누렁이 AESA 카드뉴스 · {date_str} {period_label}"
    send_cards_to_telegram(paths, target, caption=caption)

    return paths


def run_cardnews_safe(briefing_text: str, period: str = "") -> None:
    """브리핑 발송 로직과 완전히 분리된 안전 래퍼.

    카드뉴스 생성이 어떤 이유로 실패해도 예외를 밖으로 던지지 않는다
    (브리핑 발송 파이프라인에 영향 금지).
    """
    try:
        if not briefing_text or not briefing_text.strip():
            logger.warning("[카드뉴스] 입력 브리핑 텍스트가 비어 있음 — 생략")
            return
        paths = generate_cardnews(briefing_text, period=period)
        logger.info(f"[카드뉴스] 완료 ✅ ({len(paths)}장)")
    except Exception as e:
        logger.error(f"[카드뉴스] 생성 실패(브리핑 발송에는 영향 없음): {e}", exc_info=True)


# ── 직접 실행 (로컬 렌더 테스트) ──────────────────
if __name__ == "__main__":
    import sys

    # --mock: API 없이 렌더링만 검증
    if "--mock" in sys.argv:
        mock = {
            "headline": "관세 전쟁 재점화, 원화 흔들",
            "issues": [
                {"section": "정치", "title": "여야 예산안 협상 최종 결렬",
                 "summary": "여야가 내년도 예산안 협상서 이견을 좁히지 못했음. 법정 처리시한을 넘길 가능성이 커졌다고 밝혔음."},
                {"section": "경제", "title": "미 관세 확대에 코스피 급락",
                 "summary": "미국의 추가 관세 방침에 코스피가 큰 폭으로 하락했음. 원달러 환율도 장중 상승세를 보였음."},
                {"section": "AI", "title": "빅테크 AI 반도체 투자 가속",
                 "summary": "주요 빅테크가 AI 반도체 설비 투자를 대폭 늘린다고 발표했음. 국내 소부장 업계 수혜 기대가 나왔음."},
                {"section": "기타", "title": "프로야구 개막전 매진 행렬",
                 "summary": "프로야구 개막전이 전 구장 매진을 기록했음. 관중 동원 흥행이 이어질 전망이라고 전했음."},
                {"section": "경제", "title": "국제 유가 3거래일째 상승",
                 "summary": "중동 공급 우려에 국제 유가가 사흘 연속 올랐음. 정유·화학주가 강세를 보였음."},
                {"section": "정치", "title": "지방선거 D-30 판세 요동",
                 "summary": "지방선거를 한 달 앞두고 주요 격전지 판세가 흔들리고 있음. 각 당이 총력전에 돌입했다고 밝혔음."},
            ],
        }
        out_dir, date_str = _today_dir()
        html = build_html(mock["headline"], mock["issues"], date_str, "아침")
        # 디버그용 HTML 저장
        with open(os.path.join(_HERE, "_cardnews_preview.html"), "w", encoding="utf-8") as f:
            f.write(html)
        paths = render_cards(html, out_dir)
        print(f"렌더 완료: {len(paths)}장 → {out_dir}")
        for p in paths:
            print("  ", p)
    else:
        print("사용법: python cardnews.py --mock   (API 없이 렌더 테스트)")
