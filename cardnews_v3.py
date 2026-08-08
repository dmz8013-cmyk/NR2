"""
cardnews_v3.py — 누렁이 카드뉴스 최종 방향 (히어로 일러스트 60% + 설명 40%)

사용자 피드백 반영:
  1) A(크림·따뜻·손글씨) + B(굵은 라운드·스티커·주목도) 블렌드
  2) 'AI가 만든 티' 제거 → 사람 일러스트레이터가 그린 스토리북/플랫 감성
     (일관 팔레트 + 굵은 아웃라인 + 누렁이 마스코트가 매 장면 주인공)
  3) 큰 내용마다 2~3줄 설명문 추가
  4) 일러스트가 카드의 ~60%를 차지하는 대형 히어로 (작은 아바타 ❌)

레이아웃(1080×1080):
  ┌───────────────────────┐
  │  HERO 일러스트 (≈60%)   │  누렁이가 뉴스에 반응하는 역동 장면
  │  [카테고리 태그]         │
  ├───────────────────────┤  둥근 경계
  │  헤드라인 (굵은 라운드)   │
  │  2~3줄 설명 (따뜻한 톤)   │  ≈40%
  │  [푸터]                 │
  └───────────────────────┘

히어로는 Replicate Flux 생성(REPLICATE_API_TOKEN). 토큰 없으면 임시 이미지로 대체.
렌더는 cardnews.render_cards(Playwright) 재사용.
"""

import os
import base64
from datetime import datetime
from cardnews import render_cards, _logo_data_uri, _esc, _HERE, KST
from cardnews_illustrated import generate_illustration_checked, _img_data_uri  # Flux 재사용

CARD = 1080
HERO_H = 636                 # ≈59% 히어로

# 콘텐츠 히어로 일러스트 스타일 (뉴스 '장면'을 사람/사물로 표현 · 누렁이 없음)
# AI 슬롭 티 제거 → 일관 팔레트 + 두꺼운 잉크 아웃라인 + 스토리북 감성으로 '사람이 그린' 느낌
STYLE_V3 = (
    "warm hand-drawn editorial illustration, flat 2D vector art with subtle paper grain, "
    "cohesive limited palette of cream mustard-yellow terracotta sage and dusty-blue, "
    "thick confident ink outlines, cozy storybook gouache texture, "
    "expressive human characters, one clear single-scene metaphor, gentle humor, "
    "NOT 3d render, NOT photorealistic, NOT cgi, no watermark, square composition, "
    "absolutely no text no letters no numbers no words no typography no signage, "
    "all signs screens and papers blank"
)

CAT_COLOR = {
    "경제":   ("#F5B301", "#3a2a00"),
    "정치":   ("#E4572E", "#ffffff"),
    "사회국제": ("#E4572E", "#ffffff"),
    "AI":     ("#4E8FC0", "#ffffff"),
    "생활문화": ("#7FB069", "#12280f"),
    "외신":   ("#1F7A8C", "#ffffff"),
    "기타":   ("#7FB069", "#12280f"),
}

# 모든 카드(콘텐츠·표지·엔딩) 공통 푸터 — 단일 상수로만 관리할 것 (하드코딩 금지)
FOOTER_TEXT = "검색 =&gt; 누렁이 정보공유방 (카카오톡 오픈채팅 / 텔레그램)"

# 국내 뉴스 일러스트 한국인 기본값 강제 (코드단 안전망 — Claude가 국적 명시를
# 빠뜨려도 여기서 붙는다. 이미지 모델은 지시가 없으면 서양인을 기본으로 그림.)
KOREAN_DEFAULT_SUFFIX = (
    " All people in the scene are Korean East Asians with Korean features, "
    "in a modern Korean setting with Korean-style streets buildings and clothing. "
    "No Western politicians, no blond Western statesman lookalike figures."
)


def _fonts_head():
    """Pretendard 로컬 OTF 임베드 (assets/fonts/ — 리포에 포함, Docker COPY로 배포).

    CDN 의존 제거: 이전 Google Fonts 링크는 네트워크 장애 시 폰트 누락 위험.
    file:// 절대경로는 로컬(_HERE=리포)과 컨테이너(_HERE=/app) 모두에서 동작.
    """
    fonts_dir = os.path.join(_HERE, "assets", "fonts")
    faces = []
    for weight, fname in ((400, "Pretendard-Regular.otf"),
                          (600, "Pretendard-SemiBold.otf"),
                          (700, "Pretendard-Bold.otf")):
        path = os.path.join(fonts_dir, fname)
        if not os.path.exists(path):
            # 폰트 파일 누락 시 시스템 sans-serif 폴백으로 렌더는 계속되지만 반드시 로그
            import logging
            logging.getLogger("cardnews_v3").warning(f"[폰트] 파일 없음: {path}")
            continue
        faces.append(
            f"@font-face {{ font-family:'Pretendard'; font-weight:{weight}; "
            f"src: url('file://{path}') format('opentype'); }}"
        )
    return "<style>" + "\n".join(faces) + "</style>"


def _card(hero_uri, c, idx):
    bg, fg = CAT_COLOR.get(c["cat"], CAT_COLOR["기타"])
    # 표시 번호: 국내 01~10 / 외신 01~03 별도 카운트 (없으면 전체 순번)
    idx = c.get("display_no", idx)
    cat_label = "🌍 외신" if c["cat"] == "외신" else c["cat"]
    if hero_uri:
        hero_inner = f'<img class="hero-img" src="{hero_uri}" alt="">'
    else:
        # 토큰 없을 때: 어떤 장면이 그려질지 보여주는 안내 플레이스홀더(누렁이 사진 ❌)
        hero_inner = (
            f'<div class="hero-ph">🎨<div class="ph-t">일러스트 자리</div>'
            f'<div class="ph-s">{_esc(c.get("scene_ko",""))}</div></div>'
        )
    tier_html = ""
    if c.get("tier_label"):
        tier_html = f'<span class="tier">{_esc(c["tier_label"])}</span>'
    return f"""
    <section class="card v3">
      <div class="hero">
        {hero_inner}
        <div class="chips">
          <span class="cat" style="background:{bg};color:{fg}">{_esc(cat_label)} · {idx:02d}</span>
          {tier_html}
        </div>
        <div class="hero-fade"></div>
      </div>
      <div class="body fit">
        <h2 class="head">{_esc(c['title'])}</h2>
        <p class="desc">{_esc(c['desc'])}</p>
        <div class="foot">{FOOTER_TEXT}</div>
      </div>
    </section>"""


def _cover(avatar, date_str):
    return f"""
    <section class="card v3 cover">
      <div class="c-dots"></div>
      <div class="c-ava-wrap"><img class="c-ava" src="{avatar}"><span class="c-paw">🐾</span></div>
      <h1 class="c-title">누렁이 <mark class="hl">브리핑</mark></h1>
      <p class="c-sub">매일 아침, AI가 세상을 킁킁 🐕</p>
      <div class="c-tape">{_esc(date_str)} · 아침</div>
      <div class="c-foot">{FOOTER_TEXT}</div>
    </section>"""


def _ending(avatar):
    return f"""
    <section class="card v3 ending">
      <div class="c-dots"></div>
      <div class="e-ava-wrap"><img class="c-ava" src="{avatar}"></div>
      <h2 class="e-copy">오늘도 세상 소식<br><mark class="hl">잘 물어왔어요!</mark> 🐶</h2>
      <p class="c-sub">더 많은 이야기는 유튜브에서 🐾</p>
      <div class="c-tape">YOUTUBE @NR2AESA</div>
      <div class="c-foot">{FOOTER_TEXT}</div>
    </section>"""


def build_html(issues, hero_uris, date_str):
    avatar = _logo_data_uri()
    cards = [_cover(avatar, date_str)]
    cards += [_card(u, c, i + 1) for i, (c, u) in enumerate(zip(issues, hero_uris))]
    cards.append(_ending(avatar))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
{_fonts_head()}
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ background:#FFF6E4; }}
  /* 폰트 매핑: 본문=Regular(400) · 제목/라벨=SemiBold(600) · 표지/엔딩 강조=Bold(700) */
  body {{ font-family:'Pretendard','Apple SD Gothic Neo',sans-serif; font-weight:400;
          color:#4A3520; -webkit-font-smoothing:antialiased; }}
  .card {{ position:relative; width:{CARD}px; height:{CARD}px; overflow:hidden; background:#FFF6E4; }}
  mark.hl {{ background:linear-gradient(180deg,transparent 50%,#FFD54A 50%,#FFD54A 92%,transparent 92%);
             color:inherit; padding:0 8px; border-radius:4px; }}

  /* ─ 콘텐츠 카드 ─ */
  .hero {{ position:relative; width:100%; height:{HERO_H}px; overflow:hidden;
           border-bottom:10px solid #F5B301; }}
  .hero-img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .hero-ph {{ width:100%; height:100%; display:flex; flex-direction:column; align-items:center;
     justify-content:center; text-align:center; font-size:120px; gap:10px;
     background:repeating-linear-gradient(45deg,#F3E7CC,#F3E7CC 40px,#EFE0BE 40px,#EFE0BE 80px);
     color:#B79A5E; }}
  .hero-ph .ph-t {{ font-size:44px; }}
  .hero-ph .ph-s {{ font-size:34px; font-weight:400; color:#8A6A3A;
     max-width:82%; line-height:1.35; }}
  .hero-fade {{ position:absolute; left:0; right:0; bottom:0; height:120px;
     background:linear-gradient(to top, rgba(255,246,228,.9), rgba(255,246,228,0)); }}
  .chips {{ position:absolute; top:34px; left:34px; display:flex; align-items:center; gap:18px; }}
  .cat {{ font-size:40px; font-weight:600; padding:12px 34px;
          border-radius:999px; border:5px solid rgba(36,26,5,.85);
          box-shadow:5px 5px 0 rgba(36,26,5,.8); }}
  .tier {{ font-size:34px; font-weight:600; padding:12px 30px; border-radius:999px;
           background:rgba(36,26,5,.85); color:#FFD54A; }}
  .body {{ position:absolute; top:{HERO_H}px; left:0; right:0; bottom:0;
           padding:40px 56px 0; display:flex; flex-direction:column; }}
  /* 제목은 항상 한 줄: nowrap + JS 폭맞춤 축소 (긴 제목은 폰트가 줄어듦) */
  .head {{ font-size:74px; font-weight:600; line-height:1.14; letter-spacing:-2px; word-break:keep-all;
           white-space:nowrap; }}
  .desc {{ font-weight:400; font-size:41px; line-height:1.55;
           color:#6A4E2A; margin-top:22px; word-break:keep-all; }}
  /* padding-top: 설명문과의 최소 간격 보장 (12px — 기존 대비 1.5배 수준).
     margin-top:auto 가 푸터를 하단에 고정하므로 카드 높이·다른 배치는 불변. */
  .foot {{ margin-top:auto; padding-top:12px; margin-bottom:26px; font-weight:400; font-size:31px;
           color:#B08A4A; }}

  /* ─ 표지/엔딩 ─ */
  .cover, .ending {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
                     text-align:center; padding:80px; }}
  .c-dots {{ position:absolute; inset:0; background-image:radial-gradient(#EAD9B0 2px,transparent 2px);
             background-size:38px 38px; opacity:.5; }}
  .cover>*, .ending>* {{ position:relative; z-index:1; }}
  .c-ava-wrap {{ position:relative; width:330px; height:330px; margin-bottom:44px; }}
  .c-ava {{ width:330px; height:330px; border-radius:50%; object-fit:cover;
            border:14px solid #F5B301; box-shadow:0 16px 40px rgba(180,130,20,.35); }}
  .c-paw {{ position:absolute; right:-4px; bottom:18px; font-size:70px; transform:rotate(20deg); }}
  .c-title {{ font-size:130px; font-weight:700; line-height:1.1; letter-spacing:-2px; }}
  .c-sub {{ font-weight:400; font-size:52px; color:#8A6A3A; margin-top:26px; }}
  .c-tape {{ margin-top:44px; background:#F5B301; color:#4A3520; font-size:46px; font-weight:600; padding:14px 44px;
             border-radius:16px; transform:rotate(-3deg); box-shadow:0 8px 20px rgba(180,130,20,.3); }}
  .c-foot {{ margin-top:40px; font-weight:400; font-size:32px; color:#B08A4A; }}
  .e-ava-wrap {{ width:300px; height:300px; margin-bottom:40px; }}
  .e-copy {{ font-size:96px; font-weight:700; line-height:1.2; letter-spacing:-2px; }}
</style></head><body>
{''.join(cards)}
<script>
  window.__fitDone=false;
  (async function(){{ try{{ if(document.fonts&&document.fonts.ready) await document.fonts.ready; }}catch(e){{}}
    // 1) 제목 한 줄 강제: 폭이 넘치면 그 카드 제목만 폰트 축소 (하한 40px, 그 밑이면 줄바꿈 폴백)
    document.querySelectorAll('.head').forEach(function(el){{
      var s=parseFloat(getComputedStyle(el).fontSize), g=0;
      while(el.scrollWidth>el.clientWidth && s>40 && g<60){{
        s*=0.97; el.style.fontSize=s+'px'; g++; }}
      if(el.scrollWidth>el.clientWidth) el.style.whiteSpace='normal';
    }});
    // 2) 본문 높이 맞춤: 넘치면 제목·설명 동시 축소 (기존 로직)
    document.querySelectorAll('.body.fit').forEach(function(b){{
      var g=0; while(b.scrollHeight>b.clientHeight && g<60){{
        b.querySelectorAll('.head,.desc').forEach(function(el){{
          var s=parseFloat(getComputedStyle(el).fontSize); el.style.fontSize=(s*0.96)+'px'; }});
        g++; }}
    }});
    window.__fitDone=true; }})();
</script></body></html>"""


def _hero_for(issue):
    """콘텐츠 히어로 URI: Flux(뉴스 장면·누렁이 없음) 생성 + 글자 감지 시 재생성.

    국내 카드는 한국인/한국 배경 접미를 코드단에서 강제(외신 카드는 해당 국가 유지).
    실패/토큰없음 시 None → 카드가 '일러스트 자리' 안내 플레이스홀더를 표시."""
    prompt = issue.get("image_prompt")
    if prompt:
        if issue.get("cat") != "외신":
            prompt = prompt.rstrip(". ") + "." + KOREAN_DEFAULT_SUFFIX
        data = generate_illustration_checked(prompt, style_suffix=STYLE_V3, max_retries=2)
        if data is not None:
            return _img_data_uri(data)
    return None


# 샘플 3종 — 콘텐츠 히어로는 '뉴스 장면'을 사람/사물로 표현(누렁이 없음)
SAMPLE = [
    {"cat": "경제", "title": "코스피 17% ‘불기둥’ 급등! 🎉",
     "desc": "어제 코스피가 하루 만에 1001포인트나 뛰며 역대 최대 상승폭을 기록했어요. "
             "SK하이닉스가 처음으로 상한가를 찍었고 삼성전자도 26% 껑충 뛰었죠. "
             "외국인이 7조 원 넘게 사들이며 반등을 이끌었답니다.",
     "scene_ko": "환호하는 투자자들이 초록 급등 화살표 앞에서 돈다발을 던지며 기뻐하는 장면",
     "image_prompt": ("a jubilant crowd of investors in suits cheering with arms raised and throwing "
                      "cash into the air in front of a huge green upward stock-market arrow bursting "
                      "up through the floor, confetti and coins flying, euphoric market boom")},
    {"cat": "생활문화", "title": "\"돈 더 줘도 안 할래요\" Z세대의 반란",
     "desc": "승진해서 관리직이 되기 싫다는 Z세대가 늘고 있어요. 상사가 되고 싶다는 비율은 6%에 불과했죠. "
             "책임과 야근 부담이 크다는 게 이유인데, 기업들은 관리자 공백을 걱정하고 있어요.",
     "scene_ko": "나이 든 사장이 젊은 알바에게 돈다발을 내미는데 알바가 손사래 치며 나가는 장면",
     "image_prompt": ("an older boss in a suit holding out a thick stack of cash toward a young female "
                      "part-time worker who firmly pushes it away with both palms while turning her back "
                      "and walking out the door, clearly refusing, modern shop interior")},
    {"cat": "사회국제", "title": "바다가 끓자 광어가 줄줄이 🥵",
     "desc": "기록적인 폭염에 제주 양식장 수온이 28도를 넘어섰어요. 이 때문에 광어 2만 마리가 폐사했죠. "
             "폐사 여파는 시차를 두고 산지 가격에 반영될 거라고 해요.",
     "scene_ko": "밀짚모자 쓴 어민이 펄펄 끓는 양식장에 얼음을 붓고, 광어들이 힘들어하는 장면",
     "image_prompt": ("a worried fisherman in a straw hat frantically pouring a bucket of ice cubes into "
                      "a steaming boiling fish-farm pen under a giant blazing sun, exhausted flatfish "
                      "floating, hot coastal village")},
    {"cat": "사회국제", "title": "쿠팡 정보유출, 1인당 10만원 배상",
     "desc": "소비자분쟁조정위가 쿠팡의 개인정보 유출 배상 책임을 처음 인정했어요. "
             "피해자 한 사람당 10만 원씩 지급하라는 결정인데, 유출 건수 3756만 건에 그대로 적용하면 "
             "총 3조 7000억 원 규모가 됩니다.",
     "scene_ko": "찢어진 택배 상자에서 개인정보 서류가 쏟아지고 복면 쓴 도둑이 들고 달아나는 장면",
     "image_prompt": ("a giant torn cardboard delivery box spilling out hundreds of personal data "
                      "documents, a masked thief in black running away clutching the papers, a long "
                      "queue of worried customers waiting outside a corporate building")},
    {"cat": "경제", "title": "레버리지 규제 첫날, 거래 뚝 끊겼다",
     "desc": "기본예탁금이 3000만 원으로 오른 첫날, 레버리지 ETF 거래대금이 12조 원대에서 3조 원대로 "
             "주저앉았어요. 전날의 4분의 1 수준이죠. 가격은 48~60% 급등했지만 개인들은 차익 실현에 나섰어요.",
     "scene_ko": "카지노 입구에 높은 차단봉이 생겨 사람들이 막히고, 안쪽 소수만 즐기는 장면",
     "image_prompt": ("a crowd of small retail investors blocked outside a casino-like stock exchange "
                      "entrance by a tall new turnstile barrier with a huge money deposit sign, while "
                      "only a few lucky people inside ride rockets celebrating")},
    {"cat": "AI", "title": "SK하이닉스 \"적자나면 임금 조정\" 노조 반발",
     "desc": "사측이 적자가 날 경우 임금을 조정하고 자사주로 성과급을 주겠다는 안을 내놨어요. "
             "노조는 지난해 합의를 훼손하는 것이라며 수용 불가 입장입니다. "
             "8월 4일 5차 교섭에서 단체행동 가능성도 거론되고 있어요.",
     "scene_ko": "회사 측과 노조가 거대한 시소 양 끝에서 팽팽하게 맞서는 장면",
     "image_prompt": ("a giant seesaw balancing a tall pile of gold coins on one side and a group of "
                      "angry factory workers in red uniforms with folded arms on the other, a manager "
                      "in a suit tugging a lever, storm cloud with a falling arrow above")},
]


if __name__ == "__main__":
    out = os.path.join(_HERE, "output", "cardnews", "_v3_poc")
    heros = [_hero_for(s) for s in SAMPLE]
    html = build_html(SAMPLE, heros, datetime.now(KST).strftime("%Y.%m.%d"))
    with open(os.path.join(_HERE, "_cardnews_v3_preview.html"), "w", encoding="utf-8") as f:
        f.write(html)
    paths = render_cards(html, out)
    print(f"v3 POC 렌더: {len(paths)}장 → {out}")
