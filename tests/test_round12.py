"""11/10 13:00 정치 브리핑 회귀 — 주어(발언 주체)·시제(완료형) 규칙.

김민석: 이성윤 최고위원이 김 대표를 비판한 기사 → 브리핑은 '김민석 대표, 신천지 의혹 제기'로 주어 역전.
이주영: '토론회를 개최한다'(11/10 예고) 기사 → 브리핑은 '토론회 개최'로 완료형 승격.
주어 규칙은 프롬프트 규칙이라 여기서는 주입 여부만 고정한다(생성 결과 검증은 API 호출 필요).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tense_guard as tg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEE_SRC = ("응급실 수사 어떻게…의협, 11월10일 국회 토론회. 대한의사협회는 11월 10일 오전 10시 국회의원회관에서 "
           "'환자생명 보호를 위한 합리적인 의료기관 조사방안 논의' 국회 토론회를 개최한다고 밝혔다. 국민의힘 서명옥·한지아 의원과 "
           "개혁신당 이주영 의원이 공동 주최한다.")
LEE_ITEM = ("이주영 개혁신당 의원 등 국민의힘·개혁신당 의원 공동주최로 합리적 의료기관 정책 토론회 개최…"
            "소아중환자의학회 참석.")


def test_lee_completion_demoted():
    new, note = tg.check(LEE_ITEM, LEE_SRC)
    assert note and "개최 예정" in new and "토론회 개최…" not in new


def test_completion_kept_when_source_past():
    src = "국민의힘은 10일 국회에서 의료기관 조사방안 토론회를 개최했다. 앞으로 입법을 추진할 예정이다."
    new, note = tg.check(LEE_ITEM, src)
    assert note is None and new == LEE_ITEM


def test_already_future_untouched():
    item = "이주영 의원 등 공동주최 의료기관 조사방안 토론회 개최 예정."
    new, note = tg.check(item, LEE_SRC)
    assert note is None and new == item


def test_resolution_and_bill():
    new, _ = tg.check("국무회의, 청해부대 파견 동의안 의결.", "정부는 11일 국무회의에서 동의안을 의결할 예정이다.")
    assert "의결 예정" in new
    new, note = tg.check("박성훈 의원, 개인정보 보호법 개정안 발의.", "박성훈 의원은 개인정보 보호법 개정안을 대표 발의했다고 밝혔다.")
    assert note is None


def test_prompt_rules_injected():
    for f in ("political_briefing.py", "ai_briefing.py"):
        s = open(os.path.join(ROOT, f), encoding="utf8").read()
        assert "[주어 검증]" in s and "[발언 주체 / 대상자 / 발언 내용]" in s
        assert "[시제 검증]" in s and "'개최·의결·발의' 완료형" in s
