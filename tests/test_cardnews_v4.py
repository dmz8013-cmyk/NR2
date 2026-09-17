"""카드뉴스 v4 템플릿 + 승인제 파이프라인 단위 테스트 (API/DB 없이).

실행: python3 tests/test_cardnews_v4.py
"""
import sys, os, types, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('anthropic', 'requests', 'psycopg2', 'feedparser', 'replicate'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

from cardnews_v4 import build_html, SAMPLE, FOOTER_TEXT, POINT, HERO_H, SHADE_TOP, TEXT_TOP
import cardnews_daily as cd


def test_v4_structure():
    html = build_html(SAMPLE, [None] * 3, "2026.09.17", with_cover=False)
    assert html.count('class="card v4"') == 3
    assert "font-weight:800" in html and "Pretendard-ExtraBold.otf" in html
    assert "rgba(0,0,0,.88)" in html and f"top:{SHADE_TOP}px" in html
    assert SHADE_TOP == int(HERO_H * 0.6) and TEXT_TOP >= SHADE_TOP
    assert html.count(FOOTER_TEXT) == 3
    assert html.count("<li>") == 9
    assert f'style="color:{POINT["정치"]}"' in html
    assert "교섭단체 기준 20석" in html


def test_v4_escapes_and_fixed_facts_ok():
    from fixed_facts import check_text
    assert check_text(cd._issues_text(SAMPLE)) == []


def test_clean_bullets():
    assert cd._clean_bullets(["• a", "b", "c", "d"], None) == ["a", "b", "c"]
    fb = cd._clean_bullets(None, "첫 문장이에요. 둘째 문장이에요. 셋째 문장이에요.")
    assert len(fb) == 3 and fb[0] == "첫 문장이에요"


def test_source_guard():
    try:
        cd.generate_daily_cardnews("아무 텍스트", source="raw_feed")
        assert False, "원문 피드 입력이 거부되지 않음"
    except ValueError as e:
        assert "verify_pass" in str(e)


def test_template_switch(monkeypatch=None):
    os.environ["CARDNEWS_TEMPLATE"] = "v4"
    assert cd._template()[0] == "v4"
    os.environ["CARDNEWS_TEMPLATE"] = "v3"
    assert cd._template()[0] == "v3"


def test_legacy_path_disabled():
    import cardnews
    assert cardnews.run_cardnews_safe("텍스트") is None


def test_window_start_and_label():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime(2026, 9, 17, 6, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    ws = cd.window_start(now)
    assert (ws.month, ws.day, ws.hour, ws.minute) == (9, 16, 17, 0)
    assert cd._window_label(now) == "09/16 17:00 ~ 09/17 06:00 KST"


def test_ranking_cluster_and_format():
    rows = [
        {"title": "[단독] 코스피 17% 급등…역대 최대", "press": "A일보", "rank": 1, "hits": 30, "section": "경제"},
        {"title": "코스피 17% 급등 역대 최대 상승폭", "press": "B뉴스", "rank": 2, "hits": 12, "section": "경제"},
        {"title": "코스피 급등, 역대 최대 상승폭 기록(종합)", "press": "A일보", "rank": 3, "hits": 5, "section": "경제"},
        {"title": "교섭단체 요건 20석 유지 확정", "press": "C신문", "rank": 1, "hits": 40, "section": "정치"},
    ]
    cl = cd.cluster_ranking_rows(rows)
    assert len(cl) == 2
    assert cl[0]["presses"] == ["A일보", "B뉴스"] and cl[0]["hits"] == 47 and cl[0]["best_rank"] == 1
    assert "코스피" in cl[0]["title"]
    blk = cd.format_ranking_block(cl)
    assert blk.startswith("[주목도 신호 ①") and "(언론사 2곳 · 노출 47회 · 최고 1위)" in blk
    assert "2. (언론사 1곳 · 노출 40회" in blk
    assert cd.format_scoop_block([{"title": "t", "source": "s"}]).startswith("[주목도 신호 ②")
    assert cd.format_ranking_block([]) == "" and cd.format_scoop_block([]) == ""


def test_prompt_mentions_window_and_attention():
    assert "주목도 (40점)" in cd.PROMPT and "{window}" in cd.PROMPT and "basis" in cd.PROMPT


def test_v4_four_samples_and_pill():
    html = build_html(SAMPLE, [None] * 4, "2026.09.18", with_cover=False)
    assert html.count('class="card v4"') == 4 and len(SAMPLE) == 4
    assert 'class="pill"' in html and '외신·01' in html and '정치·01' in html
    assert html.count('class="bar"') == 12
    assert "설명 2~3문장" not in html   # 문단은 카드에 그리지 않음


def test_captions_and_preview_text():
    from datetime import datetime
    paths = ["c"] + [f"{i}" for i in range(4)] + ["e"]
    caps = cd._card_captions(paths, [{"desc": f"d{i}"} for i in range(4)], "HDR")
    assert caps == ["HDR", "d0", "d1", "d2", "d3", ""]
    issues = [{"cat": "정치", "display_no": 1, "title": "제목A", "desc": "x"},
              {"cat": "외신", "display_no": 1, "title": "제목B", "desc": "y"}]
    txt = cd._preview_text(datetime(2026, 9, 18, 6, 5), ["a"] * 4, issues, "v4",
                           [{"card": 2, "id": "여론조사_병기", "found": "누락: 조사기관"}], 0)
    assert "01 표지" in txt and "02 정치·01 제목A" in txt and "03 🌍외신·01 제목B 🚫" in txt and "04 엔딩" in txt
    assert "발행 보류" in txt and "/card_ok force" in txt and "x" not in txt.split("\n")[-1]
    assert len(txt) < 800


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e:
                fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
