"""2026-10-30 ㅂㅂㅂ 10/29~30 오류 7건 패치 테스트.

실행: python -m pytest tests/test_round9.py -v
  src 바인딩 · 시제가드 · 수치방향/여론조사/회의체 · 사전 TTL
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('feedparser', 'requests', 'anthropic'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

import src_bind as sb
import tense_guard as tg
import grounding as gr
import fact_checker as fc

POOL = [{"title": f"기사{i}", "description": f"본문{i}"} for i in range(1, 21)]


# ── src 바인딩 ──────────────────────────────────────────────
def test_src_parse_and_strip():
    b = "🏛️ 정치\n▪ 국회가 의결했음. {src:#12}\n▪ 무출처 항목"
    items = sb.parse(b)
    assert items[0][2] == [12] and items[1][2] == []
    assert "{src:" not in sb.strip_tags(b)


def test_src_missing_is_dropped():
    """자유통일당 논평처럼 기사 없이 생성된 항목."""
    b = "🏛️ 정치\n▪ 국회가 의결했음. {src:#1}\n▪ 자유통일당이 논평을 냈음."
    out, info = sb.enforce(b, POOL, client=None)
    assert "자유통일당" not in out and info["dropped"] and info["kept"] == 1


def test_src_multi_without_client_is_dropped():
    """위성락 지뢰+우크라 혼합처럼 src 2개 — 분리 못 하면 삭제."""
    b = "🏛️ 정치\n▪ 위성락 실장이 지뢰와 우크라를 함께 논의. {src:#3, #7}"
    out, info = sb.enforce(b, POOL, client=None)
    assert "위성락" not in out and any("별건 혼합" in d for d in info["dropped"])


def test_src_low_tag_rate_falls_back(POOL_REAL=None):
    """태그율 50% 미만이면 역매칭 폴백 (2026-10-30 C). 전량 삭제하면 안 된다."""
    pool = [{"title": "국회 본회의 예산안 의결 통과", "description": "국회가 본회의에서 예산안을 의결했다"}]
    b = "🏛️ 정치\n▪ 국회가 본회의에서 예산안을 의결했음\n▪ 전혀 무관한 내용의 항목입니다"
    out, info = sb.enforce(b, pool, client=None)
    assert info["fallback"] is True and info["tag_rate"] == 0
    assert "예산안을 의결했음" in out          # 겹침 4 이상 1건 → 유지
    assert "무관한 내용" not in out            # 매칭 0건 → 삭제


def test_src_fallback_drops_ambiguous_match():
    """폴백에서 결속 후보가 2개 이상이면 별건 혼합으로 보고 삭제."""
    pool = [{"title": "국회 예산안 의결 본회의 통과", "description": "국회 본회의 예산안 의결"},
            {"title": "국회 예산안 의결 상임위 통과", "description": "국회 예산안 의결 상임위"}]
    out, info = sb.enforce("🏛️ 정치\n▪ 국회가 예산안을 의결 통과", pool, client=None)
    assert "예산안" not in out and any("폴백 매칭" in d for d in info["dropped"])


# ── 시제 가드 ───────────────────────────────────────────────
FUTURE_SRC = "청소년올림픽 선수단 출국…31일 개막 앞두고 결전 채비"


def test_tense_result_predicate_demoted():
    new, note = tg.check("한국 선수단이 청소년올림픽에서 메달 획득", FUTURE_SRC)
    assert "획득 예정" in new and note


def test_tense_keeps_ending_grammatical():
    new, _ = tg.check("한국 선수단이 메달을 획득함", FUTURE_SRC)
    assert new.endswith("획득 예정") and "예정함" not in new


def test_tense_same_stage_untouched():
    new, note = tg.check("한국 선수단이 청소년올림픽 출전을 위해 출국함", FUTURE_SRC)
    assert note is None and new == "한국 선수단이 청소년올림픽 출전을 위해 출국함"


def test_tense_past_article_untouched():
    new, note = tg.check("한국 선수단이 메달을 획득함", "한국, 청소년올림픽 금메달 획득")
    assert note is None


# ── 수치 방향 ───────────────────────────────────────────────
PCE_SRC = "9월 PCE 물가가 전월 대비 0.3% 올라 시장 예상에 부합했다."


def test_direction_without_basis_removed():
    """'예상치 하회'(실제 부합) 유형."""
    new, notes = gr.check_direction("9월 PCE 물가가 2.8%로 예상치를 하회했음.", PCE_SRC)
    assert "하회" not in new and "2.8%" in new and notes


def test_direction_matching_source_kept():
    new, notes = gr.check_direction("9월 PCE 물가가 예상치에 부합했음.", PCE_SRC)
    assert "부합" in new and notes == []


def test_direction_tagged_as_mandatory():
    import verify_pass as vp
    r = vp.tag_item("9월 PCE 물가가 예상치를 하회했음.", set())
    assert any(x.startswith("수치 방향") for x in r) and vp.is_mandatory(r)


# ── 여론조사 4종 ────────────────────────────────────────────
def test_poll_missing_fields_listed():
    missing = gr.check_poll("이재명 대통령 긍정 평가 39%, 여당 지지도 최저치.")
    assert set(missing) == {"조사기관", "조사기간", "표본", "오차"}


def test_poll_complete_passes():
    ok = "한국갤럽 10월 27~29일 조사(1000명, 표본오차 ±3.1%p)에서 긍정 평가 39%."
    assert gr.check_poll(ok) == []


def test_poll_without_percent_not_triggered():
    assert gr.check_poll("여론조사 결과가 공개됐음.") == []


# ── 회의체 고유명사 ─────────────────────────────────────────
def test_forum_combination_mismatch_reported():
    """한미 SCM(10/28) + ADMM-Plus(10/29) 혼합."""
    bad = gr.check_forum("한미일 ADMM-Plus 에서 지뢰 문제를 논의", "한미 SCM 회의에서 합의")
    assert "ADMM-Plus" in bad and "한미일" in bad


def test_forum_match_passes():
    assert gr.check_forum("한미 SCM 에서 합의", "한미 SCM 회의에서 합의했다") == []


# ── 사전 TTL ────────────────────────────────────────────────
def test_ttl_configured_in_both_dicts():
    import json
    f = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "config", "facts.json"), encoding="utf-8"))
    fs = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "fact_sheet.json"), encoding="utf-8"))
    assert f["_meta"]["ttl_days"] == {"정당지도부": 14, "장관": 30, "선출직": 90}
    assert fs["ttl_days"] == f["_meta"]["ttl_days"]


def test_ttl_detects_expiry():
    assert fc.stale_titles("2026-10-30") == []          # 오늘 갱신분은 0건
    assert len(fc.stale_titles("2026-11-20")) > 0       # 3주 뒤엔 경과분 발생


def test_lee_junseok_title_corrected_in_both():
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    f = json.load(open(os.path.join(root, "config", "facts.json"), encoding="utf-8"))
    fs = json.load(open(os.path.join(root, "fact_sheet.json"), encoding="utf-8"))
    assert "전 개혁신당 대표" in f["인물_직함"]["이준석"]
    lj = next(x for x in fs["key_figures"] if x["name"] == "이준석")
    assert "개혁신당 대표" in lj["wrong_titles"]
    assert "이기인" in f["인물_직함"] and "비상대책위원장" in f["인물_직함"]["이기인"]



# ── A. 여론조사 보강 (2026-10-30) ────────────────────────────
POLL_SRC = "한국갤럽이 10월 27~29일 전국 성인 1000명을 대상으로 조사(표본오차 ±3.1%p)한 결과"


def test_poll_augmented_not_deleted():
    """13:00 갤럽 2건 — 삭제가 아니라 보강으로 통과해야 한다."""
    out, note = gr.augment_poll("이재명 대통령 긍정평가 39%…한국갤럽 기준 여당 지지도 최저치 기록", POLL_SRC)
    assert out and "27~29일" in out and "1000명" in out and "±3.1%p" in out
    assert "보강" in note


def test_poll_margin_prefers_value_over_label():
    out, _ = gr.augment_poll("지지율 35%로 최저치", POLL_SRC)
    assert "±3.1%p" in out and "표본오차)" not in out


def test_poll_deleted_only_when_source_lacks_fields():
    out, note = gr.augment_poll("지지율 35%로 최저치", "출처 불명 자료")
    assert out == "" and "기사에도 없어 삭제" in note


# ── D. 헤드라인 재생성 ───────────────────────────────────────
def test_headline_regenerated_from_first_item():
    import headline_guard as hg
    b = ('🔥 고정줄 🔥\n오세훈 무죄에 검찰 특검까지 전면전\n\n'
         '🟦 더불어민주당\n▪ 김민석 대표 "조희대 탄핵·국정조사, 계획대로 차근차근 진행"…방침 재확인')
    out, note = hg.regenerate_headline(b, client=None)
    assert "검찰 특검" not in out.split("\n")[1] and note


def test_headline_preserves_quote():
    import headline_guard as hg
    b = '🔥 고정줄 🔥\n임의 제목\n\n🟦 민주당\n▪ 김민석 대표 "차근차근 진행"…방침 재확인'
    out, _ = hg.regenerate_headline(b, client=None)
    assert '"차근차근 진행"' in out.split("\n")[1]


def test_headline_no_block_when_no_items():
    import headline_guard as hg
    b = "🔥 고정줄 🔥\n원래 제목\n\n🟦 민주당\n▪ 금일 주요 보도 없음"
    out, note = hg.regenerate_headline(b, client=None)
    assert note is None and out == b          # 차단 없음·원문 유지


# ── E. 병합 ──────────────────────────────────────────────────
def test_dedup_same_url_across_sections():
    import briefing_dedup as bd
    bound = [{"body": "김민석 대표 국정조사 차근차근 진행 방침 재확인", "url": "https://d/1"},
             {"body": "김민석 대표 오세훈 무죄에 국정조사 차근차근 진행 언급", "url": "https://d/1"}]
    b = ("🟦 민주당\n▪ 김민석 대표 국정조사 차근차근 진행 방침 재확인\n\n"
         "🌐 법조\n▪ 김민석 대표 오세훈 무죄에 국정조사 차근차근 진행 언급")
    out, notes = bd.dedup(b, bound)
    assert out.count("김민석") == 1 and any("URL 일치" in n for n in notes)


def test_dedup_rebuttal_pair_kept():
    import briefing_dedup as bd
    b = ("🟦 민주당\n▪ 민주당이 법무장관 인선을 비판\n"
         "▪ 국민의힘이 같은 인선을 반박하며 비판")
    out, _ = bd.dedup(b, [])
    assert out.count("▪") == 2


def test_dedup_config_thresholds():
    import json
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      "config", "briefing_dedup.json"), encoding="utf-8"))
    assert cfg["token_set_ratio"] == 85 and cfg["url_match_min_overlap"] == 4
