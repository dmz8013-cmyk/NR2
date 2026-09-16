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
