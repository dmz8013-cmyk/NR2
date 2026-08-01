"""
cardnews_illustrated.py — 이미지 중심 카드뉴스 (v2, POC 단계)

기존 cardnews.py(네이비 배경 + 텍스트)를 확장:
  - 콘텐츠 카드(핵심 이슈 6장)마다 Replicate Flux 로 편집만화 일러스트를 생성하고
    그 위에 카테고리 뱃지 + 헤드라인 + 소제목 + 불릿 3줄 + 브랜드 푸터를 오버레이.
  - 표지/엔딩은 AI 이미지 없이 고정 디자인 템플릿(스포트라이트/브랜드).
  - 렌더링은 cardnews.render_cards(Playwright)를 재사용(일러스트는 data URI 인라인).

POC 목적: 스타일·레이아웃 확정. 확정 후 select_top_issues 와 연결해 자동화.

이미지 생성:
  Replicate REPLICATE_API_TOKEN 필요(값은 로그에 남기지 않음).
  토큰이 없으면 render 시 플레이스홀더 일러스트로 대체(레이아웃 검토용).
"""

import os
import io
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cardnews_illustrated")

# 기존 모듈 재사용
from cardnews import render_cards, _logo_data_uri, _esc, _HERE, KST

# ── 브랜드/푸터 (사용자 확인 후 조정) ──────────────
BRAND_NAME = "누렁이 AESA"
COVER_TITLE = "누렁이의\n5분\n세계 스캔"          # 표지 대제목 (\n 줄바꿈)
COVER_SUB = "아는 만큼 보이는\n오늘의 세계 브리핑"
COVER_DOMAIN = "YOUTUBE.COM/@NR2AESA"
FOOTER_CTA = "카카오톡 오픈채팅 \"누렁이 정보방\" 검색!"
FOOTER_COPY = "ⓒ 누렁이 AESA"
ENDING_LINK = "https://www.youtube.com/@NR2AESA"

# 이미지 생성 모델 (flux-1.1-pro: 최고 품질. 장당 ~$0.04)
# 주의: pro 계열은 dev 계열과 입력 스펙이 다름
#   - 미지원: num_outputs / guidance / num_inference_steps / disable_safety_checker
#   - 지원  : aspect_ratio / output_format / output_quality / prompt_upsampling / safety_tolerance
FLUX_MODEL = "black-forest-labs/flux-1.1-pro"

# 편집만화 하우스 스타일 (모든 일러스트 프롬프트에 접미)
STYLE_SUFFIX = (
    "editorial cartoon illustration, Korean webtoon comic style, vibrant saturated colors, "
    "bold clean linework, cel shading with halftone dots, expressive exaggerated characters, "
    "dynamic humorous single scene, wide establishing shot, cinematic lighting, "
    "no text, no letters, no words, no watermark, square 1:1 composition"
)

CARD_W = CARD_H = 1080

# 카테고리 색 (뱃지 배경 / 소제목 색)
CATEGORY_STYLE = {
    "정치":   {"bg": "#E23B2E", "fg": "#ffffff", "sub": "#ff8b80"},
    "경제":   {"bg": "#F5B301", "fg": "#1b1200", "sub": "#ffcf4d"},
    "AI":     {"bg": "#3F6BE0", "fg": "#ffffff", "sub": "#8fb0ff"},
    "사회국제": {"bg": "#E23B2E", "fg": "#ffffff", "sub": "#ff8b80"},
    "생활문화": {"bg": "#BFE3C8", "fg": "#16351f", "sub": "#bfe3c8"},
    "기타":   {"bg": "#BFE3C8", "fg": "#16351f", "sub": "#bfe3c8"},
}


# ══════════════════════════════════════════════════
#  1. Replicate Flux 일러스트 생성
# ══════════════════════════════════════════════════
def generate_illustration(scene_prompt: str, style_suffix: str | None = None) -> bytes | None:
    """장면 프롬프트 → Flux 로 1:1 PNG 바이트 생성. 실패/토큰없음 시 None.

    style_suffix: 하우스 스타일 접미. None이면 이 모듈 기본(STYLE_SUFFIX).
    이미 스타일이 프롬프트에 포함돼 있으면 빈 문자열("")을 넘겨 중복을 피한다.
    """
    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        logger.warning("[일러스트] REPLICATE_API_TOKEN 없음 — 플레이스홀더로 대체")
        return None
    try:
        import replicate
    except ImportError:
        logger.warning("[일러스트] replicate 패키지 미설치 — 플레이스홀더로 대체")
        return None

    suffix = STYLE_SUFFIX if style_suffix is None else style_suffix
    full_prompt = f"{scene_prompt}. {suffix}" if suffix else scene_prompt

    # 429(rate limit) 대응: 결제수단 미등록 계정은 분당 6건·버스트 1건으로 제한됨.
    # 재시도 3회 + 대기. 프로덕션에서도 연속 6장 생성 시 안전장치 역할.
    import time
    client = replicate.Client(api_token=token)
    for attempt in range(1, 4):
        try:
            output = client.run(
                FLUX_MODEL,
                input={
                    "prompt": full_prompt,
                    "aspect_ratio": "1:1",
                    "output_format": "png",
                    "output_quality": 95,
                    # 프롬프트 자동 확장은 하우스 스타일을 흐트러뜨리므로 비활성화
                    "prompt_upsampling": False,
                    "safety_tolerance": 2,
                },
            )
            # replicate 반환: FileOutput(들) 또는 URL(들)
            item = output[0] if isinstance(output, (list, tuple)) else output
            if hasattr(item, "read"):            # FileOutput
                data = item.read()
            else:                                 # URL 문자열
                import requests
                data = requests.get(str(item), timeout=60).content
            logger.info(f"[일러스트] 생성 완료 ({len(data)//1024}KB) — {scene_prompt[:40]}")
            return data
        except Exception as e:
            is_rate = "429" in str(e) or "throttled" in str(e).lower()
            if is_rate and attempt < 3:
                wait = 20 * attempt
                logger.warning(f"[일러스트] 속도 제한 — {wait}초 후 재시도 ({attempt}/3)")
                time.sleep(wait)
                continue
            logger.error(f"[일러스트] 생성 실패: {e}")
            return None
    return None


# ── 글자 감지 + 자동 재생성 ───────────────────────
# Flux는 "no text" 지시를 가끔 무시하고 간판·글자를 그려 넣는다.
# Haiku 비전으로 검사해 글자가 보이면 해당 장만 재생성한다(최대 2회).
_TEXT_CHECK_MODEL = "claude-haiku-4-5-20251001"
_NO_TEXT_BOOST = (
    " Absolutely no text anywhere: no letters, no numbers, no words, no typography, "
    "no signage, no billboards, no labels; all signs, screens and papers must be blank."
)


def _image_has_text(png_bytes: bytes) -> bool:
    """Haiku 비전으로 이미지에 읽을 수 있는 글자가 있는지 검사.

    검사 불가(키 없음/오류) 시 False — 재생성 없이 그대로 사용(파이프라인 계속).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return False
    try:
        import anthropic
        from PIL import Image
        # 토큰 절약: 검사용으로 축소 JPEG 변환
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        img.thumbnail((768, 768))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        resp = client.messages.create(
            model=_TEXT_CHECK_MODEL,
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": (
                        "Does this illustration contain any readable text, letters, "
                        "numbers, or words (including on signs/screens)? "
                        "Answer with exactly one word: YES or NO.")},
                ],
            }],
        )
        answer = resp.content[0].text.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.warning(f"[일러스트] 글자 검사 실패(그대로 사용): {e}")
        return False


def generate_illustration_checked(scene_prompt: str,
                                  style_suffix: str | None = None,
                                  max_retries: int = 2) -> bytes | None:
    """생성 → 글자 감지 시 재생성(최대 max_retries회).

    재시도마다 no-text 지시를 더 강하게 붙인다.
    끝까지 글자가 남으면 마지막 결과라도 반환(카드 자체는 살린다).
    """
    last = None
    for attempt in range(max_retries + 1):
        suffix = style_suffix
        if attempt > 0 and suffix is not None:
            suffix = suffix + _NO_TEXT_BOOST
        data = generate_illustration(scene_prompt, style_suffix=suffix)
        if data is None:
            return last  # 생성 자체 실패 — 이전 결과라도
        last = data
        if not _image_has_text(data):
            return data
        logger.warning(f"[일러스트] 글자 감지 — 재생성 {attempt + 1}/{max_retries}")
    logger.warning("[일러스트] 재생성 후에도 글자 잔존 — 마지막 결과 사용")
    return last


def _placeholder_illustration(seed_text: str) -> bytes:
    """토큰 없을 때 레이아웃 검토용 플레이스홀더(그라데이션 + 라벨)."""
    from PIL import Image, ImageDraw
    # seed_text 로 색조만 살짝 바꿔 카드별 구분
    h = (sum(ord(c) for c in seed_text) % 360)
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    # 대각선 그라데이션
    import colorsys
    r1, g1, b1 = [int(x * 255) for x in colorsys.hls_to_rgb(h / 360, 0.45, 0.55)]
    r2, g2, b2 = [int(x * 255) for x in colorsys.hls_to_rgb(((h + 40) % 360) / 360, 0.25, 0.5)]
    for y in range(1024):
        t = y / 1024
        for x in range(0, 1024, 2):
            tx = (x / 1024 + t) / 2
            px[x, y] = (
                int(r1 * (1 - tx) + r2 * tx),
                int(g1 * (1 - tx) + g2 * tx),
                int(b1 * (1 - tx) + b2 * tx),
            )
            if x + 1 < 1024:
                px[x + 1, y] = px[x, y]
    d = ImageDraw.Draw(img)
    d.text((40, 40), "PLACEHOLDER\n(Flux 일러스트 자리)", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _img_data_uri(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


# ══════════════════════════════════════════════════
#  2. HTML 템플릿 (표지 + 콘텐츠 6 + 엔딩)
# ══════════════════════════════════════════════════
def _content_card_html(idx: int, issue: dict, illust_uri: str, watermark: str) -> str:
    sec = issue["section"]
    st = CATEGORY_STYLE.get(sec, CATEGORY_STYLE["기타"])
    label_html = "<br>".join(_esc(x) for x in issue.get("label_lines", [sec]))
    bullets = "".join(
        f'<li>{_esc(b)}</li>' for b in issue.get("bullets", [])[:3]
    )
    return f"""
    <section class="card content">
      <img class="illust" src="{illust_uri}" alt="">
      <div class="scrim"></div>
      <div class="badge" style="background:{st['bg']};color:{st['fg']}">
        <div class="badge-label">{label_html}</div>
        <div class="badge-rule" style="background:{st['fg']}"></div>
        <div class="badge-no">{idx:02d}</div>
      </div>
      <div class="ctext fit-box">
        <h2 class="headline">{_esc(issue['title'])}</h2>
        <div class="subhead" style="color:{st['sub']}">{_esc(issue.get('subhead',''))}</div>
        <ul class="bullets">{bullets}</ul>
      </div>
      <div class="footer-bar">
        <span class="f-cta">{_esc(FOOTER_CTA)}</span>
        <span class="f-copy">{_esc(FOOTER_COPY)}</span>
      </div>
      {watermark}
    </section>"""


def build_html(issues: list[dict], illust_uris: list[str],
               date_str: str, period_label: str) -> str:
    """표지 + 콘텐츠(일러스트) + 엔딩 카드 묶음 HTML."""
    logo = _logo_data_uri()
    watermark = f'<img class="logo" src="{logo}" alt="">' if logo else ""

    cover = f"""
    <section class="card cover">
      <div class="spot"></div>
      <div class="cover-title">{_esc(COVER_TITLE).replace(chr(10), '<br>')}</div>
      <div class="cover-rule"></div>
      <div class="cover-sub">{_esc(COVER_SUB).replace(chr(10), '<br>')}</div>
      <div class="cover-date">{_esc(date_str)} · {_esc(period_label)}</div>
      <div class="cover-domain">{_esc(COVER_DOMAIN)}</div>
      <div class="footer-bar">
        <span class="f-cta">{_esc(FOOTER_CTA)}</span>
        <span class="f-copy">{_esc(FOOTER_COPY)}</span>
      </div>
    </section>"""

    content = [
        _content_card_html(i + 1, iss, uri, watermark)
        for i, (iss, uri) in enumerate(zip(issues, illust_uris))
    ]

    ending = f"""
    <section class="card ending">
      <div class="spot"></div>
      <div class="ending-mark">🐕</div>
      <h2 class="ending-copy">매일 아침,<br>AI가 세계를 스캔합니다</h2>
      <div class="ending-link">{_esc(ENDING_LINK)}</div>
      <div class="ending-brand">{_esc(BRAND_NAME)} · 이상한 나라의 누렁이</div>
      <div class="footer-bar">
        <span class="f-cta">{_esc(FOOTER_CTA)}</span>
        <span class="f-copy">{_esc(FOOTER_COPY)}</span>
      </div>
    </section>"""

    cards = [cover] + content + [ending]

    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ background:#0b0e14; }}
  body {{ font-family:'Pretendard','Pretendard Variable',sans-serif; color:#fff;
          -webkit-font-smoothing:antialiased; }}
  .card {{ position:relative; width:{CARD_W}px; height:{CARD_H}px; overflow:hidden; background:#0b0e14; }}

  /* 공통 워터마크 로고 (콘텐츠 카드용, 푸터 위) */
  .logo {{ position:absolute; right:34px; bottom:82px; width:78px; height:78px;
           object-fit:contain; border-radius:16px; opacity:.9; z-index:5; }}

  /* ── 콘텐츠 카드 ── */
  .content .illust {{ position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }}
  .content .scrim {{ position:absolute; left:0; right:0; bottom:0; height:66%;
     background:linear-gradient(to top,
        rgba(8,10,14,.97) 26%, rgba(8,10,14,.86) 46%, rgba(8,10,14,.45) 70%, rgba(8,10,14,0) 100%); }}
  .badge {{ position:absolute; top:52px; left:52px; width:132px; padding:20px 0 22px;
            text-align:center; border-radius:10px; box-shadow:0 6px 24px rgba(0,0,0,.35); z-index:4; }}
  .badge-label {{ font-size:34px; font-weight:900; line-height:1.12; }}
  .badge-rule {{ width:52px; height:4px; margin:12px auto; opacity:.85; }}
  .badge-no {{ font-size:44px; font-weight:900; line-height:1; }}
  .ctext {{ position:absolute; left:64px; right:64px; bottom:112px; z-index:3; }}
  .headline {{ font-size:66px; font-weight:900; line-height:1.24; letter-spacing:-1.5px;
               word-break:keep-all; text-shadow:0 3px 18px rgba(0,0,0,.6); }}
  .subhead {{ font-size:42px; font-weight:800; margin-top:22px; word-break:keep-all;
              letter-spacing:-.5px; }}
  .bullets {{ margin-top:24px; list-style:none; }}
  .bullets li {{ font-size:35px; font-weight:500; color:#e9eef5; line-height:1.5;
                 padding-left:34px; position:relative; word-break:keep-all; }}
  .bullets li::before {{ content:"•"; position:absolute; left:6px; color:#F5B301; font-weight:900; }}
  .footer-bar {{ position:absolute; left:0; right:0; bottom:0; height:66px;
     background:rgba(0,0,0,.62); display:flex; align-items:center; justify-content:space-between;
     padding:0 40px; z-index:6; }}
  .f-cta {{ font-size:27px; font-weight:700; color:#fff; }}
  .f-copy {{ font-size:24px; font-weight:500; color:#c7cfda; }}

  /* ── 표지/엔딩 스포트라이트 ── */
  .cover, .ending {{ background:radial-gradient(120% 90% at 50% -10%, #2a3242 0%, #0b0e14 60%); }}
  .spot {{ position:absolute; top:-140px; left:50%; transform:translateX(-50%);
           width:520px; height:720px; z-index:0;
           background:radial-gradient(closest-side, rgba(255,255,255,.20), rgba(255,255,255,0) 72%); }}
  .cover {{ display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; }}
  .cover-title {{ position:relative; z-index:2; font-size:104px; font-weight:900; line-height:1.14;
                  letter-spacing:-2px; }}
  .cover-rule {{ position:relative; z-index:2; width:120px; height:3px; background:#8b96a8; margin:34px 0 28px; }}
  .cover-sub {{ position:relative; z-index:2; font-size:38px; font-weight:600; color:#c3ccd9; line-height:1.5; }}
  .cover-date {{ position:relative; z-index:2; margin-top:56px; font-size:40px; font-weight:800; color:#F5B301; }}
  .cover-domain {{ position:relative; z-index:2; margin-top:26px; font-size:30px; font-weight:700;
                   letter-spacing:2px; color:#8b96a8; }}

  .ending {{ display:flex; flex-direction:column; align-items:flex-start; justify-content:center; padding:96px 88px; }}
  .ending-mark {{ position:relative; z-index:2; font-size:120px; margin-bottom:20px; }}
  .ending-copy {{ position:relative; z-index:2; font-size:82px; font-weight:900; line-height:1.28;
                  letter-spacing:-1px; margin-bottom:52px; word-break:keep-all; }}
  .ending-link {{ position:relative; z-index:2; font-size:44px; font-weight:800; color:#F5B301;
                  padding:16px 0; border-top:3px solid rgba(245,179,1,.4); border-bottom:3px solid rgba(245,179,1,.4); }}
  .ending-brand {{ position:relative; z-index:2; margin-top:36px; font-size:32px; font-weight:600; color:#9fb2c8; }}
</style></head>
<body>
{''.join(cards)}
<script>
  // .fit-box: 콘텐츠 텍스트가 뱃지 하단~푸터 사이 영역을 넘지 않도록 폰트 자동 축소
  function fitAll() {{
    document.querySelectorAll('.fit-box').forEach(function(box) {{
      var guard = 0;
      // 사용 가능한 최대 높이 = 카드 하단(푸터 위)까지. bottom:112px 기준 상단 여백 확보.
      var maxH = 560;
      var els = box.querySelectorAll('.headline, .subhead, .bullets');
      function scale(f) {{ els.forEach(function(el){{
        var s = parseFloat(getComputedStyle(el).fontSize); el.style.fontSize = (s*f)+'px';
      }}); }}
      while (box.scrollHeight > maxH && guard < 60) {{ scale(0.96); guard++; }}
    }});
  }}
  window.__fitDone = false;
  (async function(){{
    try {{ if (document.fonts && document.fonts.ready) await document.fonts.ready; }} catch(e){{}}
    fitAll(); window.__fitDone = true;
  }})();
</script>
</body></html>"""


# ══════════════════════════════════════════════════
#  3. POC 오케스트레이션
# ══════════════════════════════════════════════════
def render_poc(issues: list[dict], out_dir: str) -> list[str]:
    """issues(각 항목에 image_prompt 포함) → 일러스트 생성 → 카드 렌더."""
    illust_uris = []
    for iss in issues:
        data = generate_illustration(iss["image_prompt"])
        if data is None:
            data = _placeholder_illustration(iss["title"])
        illust_uris.append(_img_data_uri(data))

    now = datetime.now(KST)
    html = build_html(issues, illust_uris, now.strftime("%Y년 %m월 %d일"), "아침")
    with open(os.path.join(_HERE, "_cardnews_v2_preview.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return render_cards(html, out_dir)


# 3장짜리 POC 샘플 (참조 카드 주제 차용, 텍스트+영어 이미지 프롬프트)
POC_SAMPLE = [
    {
        "section": "경제", "label_lines": ["경제"],
        "title": "'불기둥' 쏜 코스피, 17% 급등… 역대 최대 상승률",
        "subhead": "코스피 17.91% 급등, 6595.45 마감",
        "bullets": ["코스피 1001포인트 급등, 6595.45 마감",
                     "SK하이닉스 첫 상한가·삼성전자 26% 상승",
                     "외국인 7.2조 순매수로 반등 견인"],
        "image_prompt": ("a giant green stock-market rocket blasting off from a city skyline at dawn, "
                          "cheering businessmen in suits riding on top waving cash, fireworks and coins "
                          "flying, exuberant euphoric mood"),
    },
    {
        "section": "생활문화", "label_lines": ["생활", "문화"],
        "title": "\"돈 더 줘도 안 할래요\" 관리직 거부하는 Z세대",
        "subhead": "Z세대 관리직 기피, 언보싱 확산",
        "bullets": ["Z세대 상사 되고 싶은 비율 약 6%",
                     "승진의 책임·근무시간 부담이 기피 요인",
                     "관리자 공백 우려에 기업 고민 심화"],
        "image_prompt": ("a young hoodie-wearing Gen-Z office worker calmly declining a huge ornate "
                          "manager's throne piled with heavy books and alarm clocks, three stressed "
                          "middle managers in suits panicking in the background of a modern office"),
    },
    {
        "section": "사회국제", "label_lines": ["사회", "국제"],
        "title": "바다 끓기 시작하자 광어 줄줄이 폐사",
        "subhead": "고수온에 제주 광어 2만마리 폐사",
        "bullets": ["폭염에 양식장 표층 수온 28도 넘어",
                     "제주 광어 폐사량 2만1000여 마리로 증가",
                     "폐사 시차 두고 산지가격에 반영"],
        "image_prompt": ("an evil grinning giant sun scorching a coastal fish farm, cartoon flatfish "
                          "fainting with tongues out in a hot fish pen, a worried old fisherman in a "
                          "straw hat pouring ice cubes into the boiling water, danger sign"),
    },
]


if __name__ == "__main__":
    out_dir = os.path.join(_HERE, "output", "cardnews", "_v2_poc")
    paths = render_poc(POC_SAMPLE, out_dir)
    print(f"POC 렌더 완료: {len(paths)}장 → {out_dir}")
    for p in paths:
        print("  ", p)
