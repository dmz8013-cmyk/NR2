"""
cardnews_v4.py — 누렁이 카드뉴스 위계형 레이아웃 (2026-09-17 개편안)

v3(문단 나열: 제목 1줄 + 설명 2~3줄)에서 위계형으로 구조 변경:
  ┌───────────────────────┐
  │  HERO 일러스트 (≈58%)   │  카테고리 뱃지 좌상단(기존 유지)
  │      ┈┈ 그라데이션 ┈┈   │  이미지 하단 40% 지점부터 투명→rgba(0,0,0,.88)
  │  제목 (ExtraBold, ≤2줄) │  화면 폭 90%, 최대 임팩트
  │  부제 (SemiBold, 1줄)   │  카테고리 포인트 컬러 · 핵심 수치/인용
  │  ▪ 요점 ×3 (Regular)    │  각 25자 이내 명사형 종결
  │  [출처 바]              │  누렁이 정보공유방 (카카오톡 오픈채팅/텔레그램)
  └───────────────────────┘
텍스트는 오버레이 위에 렌더 — 텍스트 영역 배경 불투명도 0.85 이상 보장
(그라데이션 70% 지점에서 이미 .88, 히어로 아래 패널은 완전 불투명).

폰트(모두 SIL OFL 1.1 — 상업용 무료, assets/fonts/ 동봉 + LICENSE-Pretendard-OFL.txt):
  제목 Pretendard ExtraBold(800) · 부제 SemiBold(600) · 요점 Regular(400)

렌더: cardnews.render_cards(Playwright headless chromium) 재사용.
히어로: cardnews_v3._hero_for(Flux + 한국인 기본값 접미) 재사용.
전환: CARDNEWS_TEMPLATE=v4 (cardnews_daily._template) — 샘플 승인 후 기본값으로.
"""

import os
from datetime import datetime

from cardnews import render_cards, _logo_data_uri, _esc, _HERE, KST
from cardnews_v3 import _hero_for as hero_for, CAT_COLOR  # 뱃지 색·히어로 생성 재사용

CARD = 1080
HERO_H = 630                          # ≈58% 히어로
SHADE_TOP = int(HERO_H * 0.60)        # 이미지 하단 40% 지점부터 오버레이
TEXT_TOP = 556                        # 그라데이션 α≥.85 구간(≈554px~)부터 텍스트
FOOT_H = 74

FOOTER_TEXT = "누렁이 정보공유방 (카카오톡 오픈채팅/텔레그램)"

# 카테고리별 포인트 컬러 (부제·요점 마커) — 어두운 오버레이 위에서 도드라지는 톤
POINT = {
    "정치":   "#FF6B5E",
    "경제":   "#FFC72C",
    "사회국제": "#FF9F43",
    "생활문화": "#7EE081",
    "AI":     "#5CB8FF",
    "외신":   "#3DD6C8",
    "기타":   "#7EE081",
}


def fonts_head() -> str:
    """Pretendard 400/600/700/800 로컬 OTF 임베드 (assets/fonts/)."""
    fonts_dir = os.path.join(_HERE, "assets", "fonts")
    faces = []
    for weight, fname in ((400, "Pretendard-Regular.otf"),
                          (600, "Pretendard-SemiBold.otf"),
                          (700, "Pretendard-Bold.otf"),
                          (800, "Pretendard-ExtraBold.otf")):
        path = os.path.join(fonts_dir, fname)
        if not os.path.exists(path):
            import logging
            logging.getLogger("cardnews_v4").warning(f"[카드뉴스] 폰트 없음: {path}")
            continue
        faces.append(f"@font-face{{font-family:'Pretendard';font-weight:{weight};"
                     f"font-display:block;src:url('file://{path}') format('opentype');}}")
    return "<style>" + "".join(faces) + "</style>"


def _card(hero_uri, c, idx):
    bg, fg = CAT_COLOR.get(c["cat"], CAT_COLOR["기타"])
    point = POINT.get(c["cat"], POINT["기타"])
    idx = c.get("display_no", idx)
    cat_label = "🌍 외신" if c["cat"] == "외신" else c["cat"]
    if hero_uri:
        hero_inner = f'<img class="hero-img" src="{hero_uri}" alt="">'
    else:
        hero_inner = (f'<div class="hero-ph">🎨<div class="ph-s">{_esc(c.get("scene_ko", ""))}</div></div>')
    tier_html = f'<span class="tier">{_esc(c["tier_label"])}</span>' if c.get("tier_label") else ""
    bullets = (c.get("bullets") or [])[:3]
    li = "".join(f'<li><span class="mk" style="color:{point}">▪</span>{_esc(b)}</li>' for b in bullets)
    sub = c.get("subtitle") or ""
    return f"""
    <section class="card v4">
      <div class="hero">{hero_inner}</div>
      <div class="shade"></div>
      <div class="panel"></div>
      <div class="chips">
        <span class="cat" style="background:{bg};color:{fg}">{_esc(cat_label)} · {idx:02d}</span>
        {tier_html}
      </div>
      <div class="txt">
        <h2 class="title">{_esc(c['title'])}</h2>
        <p class="sub" style="color:{point}">{_esc(sub)}</p>
        <ul class="pts">{li}</ul>
      </div>
      <div class="footbar"><span>{_esc(FOOTER_TEXT)}</span></div>
    </section>"""


def _cover(avatar, date_str):
    ava = f'<img class="c-ava" src="{avatar}">' if avatar else ""
    return f"""
    <section class="card v4 cover">
      <div class="c-dots"></div>
      <div class="c-ava-wrap">{ava}</div>
      <h1 class="c-title">누렁이 <mark class="hl">브리핑</mark></h1>
      <p class="c-sub">매일 아침, AI가 세상을 킁킁 🐕</p>
      <div class="c-tape">{_esc(date_str)} · 아침</div>
      <div class="footbar"><span>{_esc(FOOTER_TEXT)}</span></div>
    </section>"""


def _ending(avatar):
    ava = f'<img class="c-ava" src="{avatar}">' if avatar else ""
    return f"""
    <section class="card v4 ending">
      <div class="c-dots"></div>
      <div class="c-ava-wrap">{ava}</div>
      <h2 class="e-copy">오늘도 세상 소식<br><mark class="hl">잘 물어왔어요!</mark> 🐶</h2>
      <p class="c-sub">더 많은 이야기는 유튜브에서 🐾</p>
      <div class="c-tape">YOUTUBE @NR2AESA</div>
      <div class="footbar"><span>{_esc(FOOTER_TEXT)}</span></div>
    </section>"""


def build_html(issues, hero_uris, date_str, with_cover=True):
    avatar = _logo_data_uri()
    cards = [_cover(avatar, date_str)] if with_cover else []
    cards += [_card(u, c, i + 1) for i, (c, u) in enumerate(zip(issues, hero_uris))]
    if with_cover:
        cards.append(_ending(avatar))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
{fonts_head()}
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ background:#0E0F13; }}
  body {{ font-family:'Pretendard','Apple SD Gothic Neo',sans-serif; font-weight:400; color:#fff;
          -webkit-font-smoothing:antialiased; }}
  .card {{ position:relative; width:{CARD}px; height:{CARD}px; overflow:hidden; background:#0E0F13; }}
  mark.hl {{ background:linear-gradient(180deg,transparent 55%,#FFC72C 55%,#FFC72C 92%,transparent 92%);
             color:inherit; padding:0 8px; border-radius:4px; }}

  /* ─ 히어로 + 오버레이 ─ */
  .hero {{ position:absolute; top:0; left:0; width:100%; height:{HERO_H}px; overflow:hidden; }}
  .hero-img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .hero-ph {{ width:100%; height:100%; display:flex; flex-direction:column; align-items:center;
     justify-content:center; text-align:center; font-size:110px; gap:10px; color:#8b8f9a;
     background:repeating-linear-gradient(45deg,#2a2d36,#2a2d36 40px,#23262e 40px,#23262e 80px); }}
  .hero-ph .ph-s {{ font-size:30px; max-width:80%; line-height:1.4; }}
  /* 이미지 하단 40% 지점부터: 투명 → rgba(0,0,0,.88). 70% 지점에서 이미 .88 도달 →
     텍스트 시작선(TEXT_TOP) 아래는 항상 불투명도 .85 이상 */
  .shade {{ position:absolute; left:0; right:0; top:{SHADE_TOP}px; height:{HERO_H - SHADE_TOP}px;
     background:linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,.88) 70%, rgba(0,0,0,.88) 100%); }}
  .panel {{ position:absolute; left:0; right:0; top:{HERO_H}px; bottom:0; background:#0E0F13; }}

  /* ─ 뱃지(기존 유지) ─ */
  .chips {{ position:absolute; top:34px; left:34px; display:flex; align-items:center; gap:18px; }}
  .cat {{ font-size:40px; font-weight:600; padding:12px 34px; border-radius:999px;
          border:5px solid rgba(36,26,5,.85); box-shadow:5px 5px 0 rgba(36,26,5,.8); }}
  .tier {{ font-size:34px; font-weight:600; padding:12px 30px; border-radius:999px;
           background:rgba(0,0,0,.72); color:#FFC72C; }}

  /* ─ 텍스트 위계 ─ */
  .txt {{ position:absolute; left:54px; width:{int(CARD * 0.9)}px; top:{TEXT_TOP}px; bottom:{FOOT_H + 18}px;
          display:flex; flex-direction:column; justify-content:flex-start; overflow:hidden; }}
  .txt > * {{ flex-shrink:0; }}
  .title {{ font-weight:800; font-size:78px; line-height:1.14; letter-spacing:-2.5px;
            word-break:keep-all; text-shadow:0 2px 12px rgba(0,0,0,.45); }}
  .sub {{ font-weight:600; font-size:43px; line-height:1.25; letter-spacing:-1px; margin-top:14px;
          white-space:nowrap; overflow:hidden; }}
  .pts {{ list-style:none; margin-top:24px; display:flex; flex-direction:column; gap:8px; }}
  .pts li {{ font-weight:400; font-size:35px; line-height:1.4; color:rgba(255,255,255,.9);
             white-space:nowrap; overflow:hidden; word-break:keep-all; }}
  .pts .mk {{ display:inline-block; width:44px; }}

  /* ─ 출처 바 ─ */
  .footbar {{ position:absolute; left:0; right:0; bottom:0; height:{FOOT_H}px; display:flex; align-items:center;
              justify-content:center; background:rgba(255,255,255,.06); border-top:1px solid rgba(255,255,255,.14);
              font-weight:400; font-size:28px; color:rgba(255,255,255,.62); letter-spacing:-.3px; }}

  /* ─ 표지/엔딩 ─ */
  .cover, .ending {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
                     text-align:center; padding:80px 80px {FOOT_H + 40}px; }}
  .c-dots {{ position:absolute; inset:0; background-image:radial-gradient(#2b2f3a 2px,transparent 2px);
             background-size:38px 38px; opacity:.7; }}
  .cover>*, .ending>* {{ position:relative; z-index:1; }}
  .c-ava-wrap {{ width:330px; height:330px; margin-bottom:44px; }}
  .c-ava {{ width:330px; height:330px; border-radius:50%; object-fit:cover;
            border:14px solid #FFC72C; box-shadow:0 16px 40px rgba(0,0,0,.5); }}
  .c-title {{ font-size:130px; font-weight:800; line-height:1.1; letter-spacing:-3px; }}
  .c-sub {{ font-weight:400; font-size:50px; color:rgba(255,255,255,.7); margin-top:26px; }}
  .c-tape {{ margin-top:44px; background:#FFC72C; color:#1a1a1a; font-size:46px; font-weight:600;
             padding:14px 44px; border-radius:16px; transform:rotate(-3deg); }}
  .e-copy {{ font-size:96px; font-weight:800; line-height:1.2; letter-spacing:-2px; }}
</style></head><body>
{''.join(cards)}
<script>
  window.__fitDone=false;
  (async function(){{ try{{ if(document.fonts&&document.fonts.ready) await document.fonts.ready; }}catch(e){{}}
    function shrink(el, fits, min){{ var s=parseFloat(getComputedStyle(el).fontSize), g=0;
      while(!fits(el) && s>min && g<80){{ s*=0.97; el.style.fontSize=s+'px'; g++; }} }}
    // 제목: 2줄 이내(line-clamp 로 잘리기 전에 폰트 축소, 하한 52px)
    document.querySelectorAll('.title').forEach(function(el){{
      shrink(el, function(e){{ var lh=parseFloat(getComputedStyle(e).lineHeight);
        return e.scrollHeight <= lh*2 + 4; }}, 52); }});
    // 부제·요점: 각 1줄 (폭 초과 시 축소)
    document.querySelectorAll('.sub, .pts li').forEach(function(el){{
      shrink(el, function(e){{ return e.scrollWidth <= e.clientWidth; }}, 26); }});
    // 블록 전체 높이 초과 시 제목·부제·요점 동시 축소 (하단 출처 바 침범 방지)
    document.querySelectorAll('.txt').forEach(function(b){{
      var g=0; while(b.scrollHeight>b.clientHeight && g<40){{
        b.querySelectorAll('.title,.sub,.pts li').forEach(function(el){{
          var s=parseFloat(getComputedStyle(el).fontSize); el.style.fontSize=(s*0.96)+'px'; }});
        g++; }} }});
    window.__fitDone=true; }})();
</script></body></html>"""


# ── 샘플 3장(정치/경제/생활문화) — 디자인 검토용 가상 문구 ──
SAMPLE = [
    {"cat": "정치", "tier_label": "핵심", "display_no": 1,
     "title": "교섭단체 기준 20석, 그대로 간다",
     "subtitle": "국회법 33조 · 요건 20석 유지",
     "bullets": ["여야, 요건 완화 개정안 처리 불발", "소수정당 '진입 장벽' 반발", "다음 임시국회서 재논의 전망"],
     "scene_ko": "국회 본회의장 문 앞에서 소수 의원들이 두드리고 안에서는 표결 버튼을 누르는 장면",
     "image_prompt": ("a small group of Korean lawmakers knocking on a tall closed assembly-hall door "
                      "while inside rows of Korean legislators press voting buttons, warm chamber light, "
                      "blank nameplates, blank screens")},
    {"cat": "경제", "tier_label": "오늘의 1면", "display_no": 2,
     "title": "코스피 하루 17% '불기둥' 급등",
     "subtitle": "역대 최대 상승폭 +1001p",
     "bullets": ["SK하이닉스 사상 첫 상한가", "삼성전자 26% 급등 마감", "외국인 7조 원 순매수"],
     "scene_ko": "환호하는 투자자들이 초록 급등 화살표 앞에서 돈다발을 던지며 기뻐하는 장면",
     "image_prompt": ("a jubilant crowd of Korean investors in suits cheering with arms raised and throwing "
                      "cash into the air in front of a huge green upward stock-market arrow bursting "
                      "up through the floor of a Seoul trading hall, confetti and coins flying")},
    {"cat": "생활문화", "tier_label": "생활", "display_no": 3,
     "title": "\"돈 더 줘도 승진 싫어요\"",
     "subtitle": "Z세대 '상사 되고 싶다' 6%",
     "bullets": ["관리직 기피, 책임·야근 부담", "기업들 관리자 공백 우려", "'수평 성장' 선호 확산"],
     "scene_ko": "나이 든 사장이 젊은 직원에게 돈다발을 내미는데 직원이 손사래 치며 나가는 장면",
     "image_prompt": ("an older Korean boss in a suit holding out a thick stack of cash toward a young Korean "
                      "female office worker who firmly pushes it away with both palms while turning her back "
                      "and walking out the door, modern Seoul office interior, blank signs")},
]


if __name__ == "__main__":
    import sys
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_HERE, ".env"))
    except Exception:
        pass
    out = os.path.join(_HERE, "output", "cardnews", "_v4_samples")
    heros = [None if "--no-flux" in sys.argv else hero_for(s) for s in SAMPLE]
    html = build_html(SAMPLE, heros, datetime.now(KST).strftime("%Y.%m.%d"), with_cover=False)
    with open(os.path.join(_HERE, "_cardnews_v4_preview.html"), "w", encoding="utf-8") as f:
        f.write(html)
    paths = render_cards(html, out)
    print(f"v4 샘플 렌더: {len(paths)}장 → {out}")
    if "--send" in sys.argv:
        from cardnews import send_cards_to_telegram
        target = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
        ok = send_cards_to_telegram(paths, target,
                                    caption="🎨 카드뉴스 v4 디자인 샘플 3장 (정치/경제/생활문화 · 검토용 가상 문구)")
        print("DM 전송:", "성공" if ok else "실패")
