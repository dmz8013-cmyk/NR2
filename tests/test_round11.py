"""2026-11-03 ㅂㅂㅂ 지시 F·G 패치 테스트.

실행: python -m pytest tests/test_round11.py -v
  F 빈 출처 표기 잔여물 · G 헤드라인-본문 정합 / 헤드라인 소스 36h
"""
import sys
import os
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('feedparser', 'requests', 'anthropic'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

import src_bind as sb
import src_render_guard as srg
import headline_guard as hg

KST = ZoneInfo("Asia/Seoul")


# ── F. 빈 출처 표기 ──────────────────────────────────────────
def test_f_doubled_brace_tag_is_fully_stripped():
    """11/2~11/3 전 회차 결함의 원본 — 모델이 {{src:#12}} 를 달았다."""
    b = "🟦 민주당\n▪ 국민의힘, 양준모 교수 임명 {{src:#12}}"
    out = sb.strip_tags(b)
    assert out.endswith("임명") and "{" not in out and "}" not in out


def test_f_single_brace_tag_still_stripped():
    out = sb.strip_tags("🟦 민주당\n▪ 국회가 예산안을 의결했음. {src:#12}")
    assert out.endswith("의결했음.") and "{" not in out


def test_f_doubled_brace_ids_are_parsed():
    """태그율 계산이 두 겹 중괄호에도 살아 있어야 폴백으로 떨어지지 않는다."""
    items = sb.parse("🟦 민주당\n▪ 국회가 의결했음. {{src:#12}}")
    assert items[0][2] == [12] and "{" not in items[0][1]


def test_f_prompt_rule_uses_single_braces():
    """f-string 의 값으로 들어가므로 두 겹이면 모델이 그대로 베낀다."""
    assert "{src:#번호}" in sb.PROMPT_RULE and "{{" not in sb.PROMPT_RULE


def test_f_residue_removed_and_counted():
    t = "🟦 민주당\n▪ 첫 항목 {}\n▪ 둘째 항목\n▪ 셋째 항목 []"
    out, removed, total = srg.clean(t)
    assert removed == 2 and total == 3
    assert out.count("{}") == 0 and out.count("[]") == 0
    assert "▪ 둘째 항목" in out


def test_f_mid_sentence_brackets_untouched():
    t = "▪ 보고서(주: 표 {} 참조)에 수치가 없음"
    out, removed, _ = srg.clean(t)
    assert removed == 0 and out == t


def test_f_non_item_lines_untouched():
    t = "🟦 민주당 {}\n▪ 정상 항목"
    out, removed, _ = srg.clean(t)
    assert removed == 0 and out == t


def test_f_none_tail_removed():
    out, removed, _ = srg.clean("▪ 항목 본문 None")
    assert removed == 1 and out.strip() == "▪ 항목 본문"


def test_f_render_src_emits_nothing_for_empty():
    assert srg.render_src({}) == "" and srg.render_src([]) == "" and srg.render_src(None) == ""
    assert srg.render_src({"url": "https://d/1"}).strip() == "https://d/1"


def test_f_over_rate():
    assert srg.over_rate(6, 10) is True          # 60% — 경보
    assert srg.over_rate(5, 10) is False         # 50% — 경보 아님
    assert srg.over_rate(0, 0) is False


def test_f_gate_counts_and_logs(caplog):
    import gate
    b = ("🟦 더불어민주당\n▪ 김민석 대표가 당-노총 고위급정책협의회를 개최했음 {}\n"
         "▪ 신장식 대표가 합당론에 선을 그음 {}")
    pool = [{"title": "김민석 대표 당-노총 고위급정책협의회 개최",
             "description": "김민석 대표와 김동명 위원장이 고위급정책협의회를 개최했다",
             "link": "https://d/1", "pub_date": datetime.now(KST).isoformat()},
            {"title": "신장식 합당론에 선 그음", "description": "신장식 대표가 합당론에 선을 그었다",
             "link": "https://d/2", "pub_date": datetime.now(KST).isoformat()}]
    out, info = gate.enforce(b, pool, "political_afternoon")
    assert info["check_counts"]["F"] == 2 and info["src_empty"] == 2
    assert "{}" not in out
    assert any("src_empty: 2" in r.message for r in caplog.records if "[내용검사]" in r.message)


# ── G. 헤드라인 정합 ─────────────────────────────────────────
BODY = ("🔥 고정줄 🔥\n{head}\n\n🟦 더불어민주당\n"
        '▪ 김민석 대표 "국정조사 차근차근 진행"…방침 재확인\n'
        "▪ 민주당이 시정연설 예산안 처리를 강조")


def test_g_mismatched_headline_regenerated():
    b = BODY.format(head="북한 미사일 발사에 합참 대응")
    out, note = hg.verify_against_body(b, client=None)
    assert note and "부정합" in note
    assert "미사일" not in out.split("\n")[1]


def test_g_matching_headline_untouched():
    b = BODY.format(head='김민석 "국정조사 차근차근 진행" 재확인')
    out, note = hg.verify_against_body(b, client=None)
    assert note is None and out == b


def test_g_one_missing_noun_is_tolerated():
    """3개 중 1개만 없으면 통과 — 과잉 재생성 방지."""
    b = BODY.format(head="김민석 국정조사 속도전")
    assert len(hg.body_missing("김민석 국정조사 속도전", b)) == 1
    _, note = hg.verify_against_body(b, client=None)
    assert note is None


def test_g_core_nouns_skip_function_words():
    ns = hg.core_nouns("이재명 대통령 시정연설 관련 비판 이번 지난")
    assert "관련" not in ns and "이번" not in ns and "비판" not in ns
    assert "시정연설" in ns


def test_g_no_headline_line_is_noop():
    """아침/저녁 브리핑은 🔥 줄이 없다 — 손대지 않는다."""
    b = "아침 누렁이 정보공유방 브리핑 | 2026년 11월 03일 06:00\n\n🏛️ 정치\n▪ 항목"
    out, note = hg.verify_against_body(b, client=None)
    assert note is None and out == b


def test_g_fresh_drops_stale_breaking_article():
    now = datetime.now(KST)
    arts = [{"title": "북한 미사일 발사", "pub_date": (now - timedelta(hours=80)).isoformat()},
            {"title": "합참 대응 태세", "pub_date": (now - timedelta(hours=5)).isoformat()}]
    kept = hg.fresh(arts, now=now)
    assert [a["title"] for a in kept] == ["합참 대응 태세"]


def test_g_fresh_drops_unknown_pub_time():
    assert hg.fresh([{"title": "시각 불명 기사"}]) == []
