"""브리핑 공용 레이아웃(briefing_layout) + 표현 규칙 테스트.

실행: python -m pytest tests/test_briefing_layout.py -v
4개 발행(정보공유방 06/18시, 정치 13/22시) 렌더링 결과를 검증:
상단 출처 2링크 · 하단 참고 2링크 · 금지 표현 0건 · ───── 부재.
"""
import sys
import os
import re
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ai_briefing 임포트용 외부 의존성 스텁 (금지 정규식만 쓰므로 무해)
for m in ('feedparser', 'requests', 'anthropic'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

from briefing_layout import apply_layout, load_layout, SECTION_HEADER_RE
from ai_briefing import BANNED_PREDICATE_RE

HR_RE = re.compile(r'[─—–]{3,}')


def _ai_fixture(period, time_str):
    """정보공유방 브리핑 원문 — 구식 출처·nr2 푸터·헤더 아래 구분선 포함."""
    return f"""{period} 누렁이 정보공유방 브리핑 | 2026년 09월 15일 {time_str}
출처: https://t.me/gazzzza2025
(실시간 텔레그램 정보방)

🏛️ 정치/시사
─────
▪ 국회 법제사법위원회가 A법 개정안을 재석 15인 중 찬성 9인으로 의결했음.
▪ 감사원이 B부처 정기감사에서 예산 12억 원의 집행 부적정 사례 3건을 통보했음.

💰 경제/산업
▪ 한국은행이 기준금리를 연 3.00%로 동결했음.
📈 시세(Upbit 기준): 비트코인 1억원(+1.0%)

🤖 AI/기술
▪ 오픈AI가 신모델을 공개했음.

🎯 기타
▪ 기상청이 태풍 경로를 발표했음.

출처: https://buly.kr/7mBN720
(실시간 카카오톡 오픈채팅)

━━━━━━━━━━━━━━━━
📖 오늘 브리핑 전문 + 심층 토론
👉 https://nr2.kr
━━━━━━━━━━━━━━━━"""


def _political_fixture(time_label):
    """정치 브리핑 원문 — 구식 '-' 불릿·출처 블록·⸻ 포함."""
    return f"""🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(260915 {time_label})】🔥
여야 격돌, 오늘의 정치권 핵심 정리

출처: https://buly.kr/7mBN720
(실시간 카카오톡 오픈채팅)

⸻⸻⸻⸻

🇰🇷 이재명 정부 🇰🇷
─────
- 대통령실이 2차 공공기관 이전 계획을 발표… 지역 반발 점화
- 국무회의서 예산안 의결

⸻⸻⸻⸻

🟦 더불어민주당 🟦
- 지도부가 법안 처리 시한을 확정

⸻⸻⸻⸻

🟥 국민의힘 🟥
- 원내대표가 정부 예산안을 강도 높게 비판

⸻⸻⸻⸻

출처: https://t.me/gazzzza2025
(텔레그램 실시간 정보방)"""


FIXTURES = {
    'ai_morning': _ai_fixture('🌅 아침', '06:00'),
    'ai_evening': _ai_fixture('🌆 저녁', '18:00'),
    'political_afternoon': _political_fixture('13:00'),
    'political_evening': _political_fixture('22:00'),
}


def _rendered():
    return {kind: apply_layout(raw) for kind, raw in FIXTURES.items()}


# ── 4개 발행 공통 검증 ──────────────────────────────
def test_header_two_links_below_title():
    cfg = load_layout()
    for kind, out in _rendered().items():
        lines = out.split('\n')
        # 제목 블록(1~2줄) 다음: 빈 줄 → 헤더 3줄(출처: + 링크 2)
        title_len = 2 if kind.startswith('political') else 1
        assert lines[title_len] == '', (kind, lines[:5])
        got = lines[title_len + 1: title_len + 1 + len(cfg['header_lines'])]
        assert got == cfg['header_lines'], (kind, got)
        assert 'buly.kr/7mBN720' in got[1] and 't.me/gazzzza2025' in got[2]


def test_footer_two_reference_links():
    for kind, out in _rendered().items():
        tail = '\n'.join(out.split('\n')[-10:])
        assert '참고: ' in tail, kind
        assert 'https://t.me/gazzzza2025' in tail
        assert '(실시간 텔레그램 국내 언론 최신기사방)' in tail
        assert 'https://t.me/nr2aesa' in tail
        assert '(실시간 텔레그램 주요 외신방)' in tail
        assert tail.rstrip().endswith('━━━━━━━━━━━━━━━━'), kind
        # 구식 nr2.kr 푸터·본문 내 출처 잔재 없음 (템플릿 '출처: ' 1회만)
        assert '심층 토론' not in out and '👉' not in out
        assert out.count('출처') == 1, kind


def test_no_header_underline_rule():
    for kind, out in _rendered().items():
        assert not HR_RE.search(out), (kind, 'header 아래 ───── 잔존')
        # 섹션 헤더 다음 줄은 빈 줄 1개
        lines = out.split('\n')
        for i, ln in enumerate(lines):
            if SECTION_HEADER_RE.match(ln.strip()):
                assert lines[i + 1] == '', (kind, ln)
                assert lines[i + 2].strip() != '', (kind, ln)


def test_sections_separated_and_bullets_unified():
    sep = load_layout()['section_separator']
    for kind, out in _rendered().items():
        n_headers = sum(1 for ln in out.split('\n') if SECTION_HEADER_RE.match(ln.strip()))
        assert n_headers >= 3, kind
        assert out.count(sep) == n_headers - 1, (kind, '섹션 사이 ⸻ 수 불일치')
        # 항목은 ▪ 1줄 — 정치 브리핑 '-' 불릿도 ▪ 로 통일됨
        assert not re.search(r'^\s*- ', out, re.M), kind
        assert '▪' in out


def test_no_banned_expressions_in_rendered_output():
    for kind, out in _rendered().items():
        for ln in out.split('\n'):
            if ln.strip().startswith('▪'):
                assert not BANNED_PREDICATE_RE.search(ln), (kind, ln)


# ── C1: 금지 표현 정규식이 루머 술어를 전부 잡는지 ──
def test_banned_regex_catches_rumor_predicates():
    for s in ('구속영장 청구 방침으로 전해졌다', '내주 발표로 전해짐',
              '교체설이 전해진다', '사퇴 가능성이 알려졌다', '이견이 있는 것으로 알려짐',
              '합의가 임박한 것으로 보인다', '연내 처리 어렵다는 관측'):
        assert BANNED_PREDICATE_RE.search(s), s
    for s in ('국회가 법안을 가결했음', '검찰이 압수수색에 착수', '예산안 의결'):
        assert not BANNED_PREDICATE_RE.search(s), s
