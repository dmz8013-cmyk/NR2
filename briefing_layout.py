"""briefing_layout.py — 브리핑 2종 공용 발송 레이아웃 (config/briefing_layout.json).

정보공유방 브리핑(06:00/18:00)과 정치 브리핑(13:00/22:00) 4개 발행이 같은
헤더·푸터·섹션 규칙을 쓰도록 발송 직전에 결정론적으로 재조립한다:

  [제목·부제(1~2줄)]
  (빈 줄)
  출처: / 카톡·텔레 2링크          ← header_lines
  (빈 줄)
  섹션 헤더
  (빈 줄 1개)
  ▪ 항목 (항목 사이 빈 줄 없음)
  (빈 줄) ⸻⸻⸻⸻ (빈 줄)            ← 섹션 사이
  ...
  (빈 줄)
  ━━━ / 참고: 텔레 2링크 / ━━━     ← footer_lines

모델이 써넣은 구식 출처·nr2.kr 푸터·섹션 헤더 아래 구분선(─────)은 제거.
설정 로드 실패 시 코드 내 기본값 사용 — 어떤 실패도 발송을 막지 않는다.
"""
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, 'config', 'briefing_layout.json')

_DEFAULTS = {
    'header_lines': [
        '출처: ',
        'https://buly.kr/7mBN720 (실시간 오픈카톡 정보방)',
        'https://t.me/gazzzza2025 (실시간 텔레그램 정보방)',
    ],
    'footer_lines': [
        '━━━━━━━━━━━━━━━━', '',
        '참고: ',
        'https://t.me/gazzzza2025', '(실시간 텔레그램 국내 언론 최신기사방)',
        'https://t.me/nr2aesa', '(실시간 텔레그램 주요 외신방)',
        '', '━━━━━━━━━━━━━━━━',
    ],
    'section_separator': '⸻⸻⸻⸻',
    'allowed_endings': ['확정', '체결', '비판', '기각'],
}


def load_layout() -> dict:
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return {k: data.get(k, v) for k, v in _DEFAULTS.items()}
    except Exception as e:
        logger.warning(f'[레이아웃] 설정 로드 실패 — 기본값 사용: {e}')
        return dict(_DEFAULTS)


def allowed_endings() -> list[str]:
    return load_layout()['allowed_endings']


# 아침/저녁(정보공유방) 브리핑 4개 섹션 — 이모지로 식별한다.
# 이름('기타')으로 맞추면 정치 브리핑의 '🎸 비교섭단체 및 기타 정치'와 충돌한다.
GENERAL_SECTION_EMOJI = ('🏛️', '💰', '🤖', '🎯')
EMPTY_SECTION_LINE = '▪ 이 시간대 주요 이슈 없음 — 속보 발생 시 즉시 공유'

# 섹션 헤더: 두 봇의 섹션 이모지로 시작하는 줄
SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')
# 섹션 헤더 아래 구분선(─·—·– 만으로 된 줄) — ━(푸터)·⸻(섹션 구분)는 제외
_HR_RE = re.compile(r'^[\s]*[─—–-]{3,}[\s]*$')
_SEP_CHARS_RE = re.compile(r'^[\s⸻]+$')

# 모델이 써넣는 구식 출처·푸터 줄 — 템플릿 삽입 전에 제거
_LEGACY_PATTERNS = (
    lambda s: s.startswith('출처:') or s.startswith('출처 :') or s == '출처',
    lambda s: s.startswith('참고:') or s.startswith('참고 :'),
    lambda s: s.startswith('(실시간') or s.startswith('(텔레그램'),
    lambda s: 'buly.kr/7mBN720' in s,
    lambda s: 't.me/gazzzza2025' in s or 't.me/nr2aesa' in s,
    lambda s: '심층 토론' in s or '👉' in s or s == 'https://nr2.kr',
    lambda s: set(s) == {'━'},
)


def _is_legacy(line: str) -> bool:
    s = line.strip()
    return bool(s) and any(p(s) for p in _LEGACY_PATTERNS)


def fill_empty_general_sections(body: list[str]) -> list[str]:
    """본문이 0건인 아침/저녁 섹션 헤더 아래에 안내 한 줄을 넣는다 (2026-10-27).

    10/27 18:00 저녁판에서 '🏛️ 정치/시사' 가 헤더만 남고 비어 나갔다 — 수집은
    15건 정상이었으나 초안의 정치 항목 4건이 전부 verify_pass 에서 제외됐고,
    ai_briefing 에는 정치 브리핑의 mark_empty_sections 같은 장치가 없었다.

    body 는 apply_layout 이 조립한 '헤더, 빈 줄, 항목…' 구조다. 헤더 블록을
    통째로 다시 쌓아 간격이 어긋나지 않게 한다.
    """
    # 헤더 위치로 블록 분할
    idx = [i for i, ln in enumerate(body) if SECTION_HEADER_RE.match(ln.strip())]
    if not idx:
        return body
    out = body[:idx[0]]
    for n, start in enumerate(idx):
        stop = idx[n + 1] if n + 1 < len(idx) else len(body)
        header = body[start]
        rest = body[start + 1:stop]
        is_general = header.strip().startswith(GENERAL_SECTION_EMOJI)
        has_item = any(ln.strip().startswith('▪') for ln in rest)
        if is_general and not has_item:
            # rest 선두의 빈 줄은 헤더 간격, 그 뒤는 섹션 구분선 블록(''·⸻·'')이다.
            # 구분선을 보존해야 섹션 경계가 유지된다.
            lead = 0
            while lead < len(rest) and not rest[lead].strip():
                lead += 1
            out += [header, '', EMPTY_SECTION_LINE] + rest[max(0, lead - 1):]
            logger.warning(f'[레이아웃] 빈 섹션 안내 삽입: {header.strip()}')
        else:
            out += [header] + rest
    return out


def apply_layout(text: str) -> str:
    """발송 직전 레이아웃 재조립. 실패 시 원문 반환(발송 우선)."""
    try:
        cfg = load_layout()
        sep = cfg['section_separator']
        lines = [ln.rstrip() for ln in (text or '').split('\n')]

        # 1) 구식 출처/푸터/구분선(─────) 제거
        lines = [ln for ln in lines if not _is_legacy(ln) and not _HR_RE.match(ln)]

        # 2) 제목·부제 블록: 선두의 비어있지 않은 줄 최대 2개
        #    (섹션 헤더·⸻ 줄을 만나면 그 전까지)
        title, i = [], 0
        while i < len(lines) and len(title) < 2:
            s = lines[i].strip()
            if not s:
                if title:
                    break
                i += 1
                continue
            if SECTION_HEADER_RE.match(s) or _SEP_CHARS_RE.match(s):
                break
            title.append(lines[i])
            i += 1

        # 3) 본문 섹션 재조립 — 헤더 다음 빈 줄 1개, 항목 사이 빈 줄 없음,
        #    섹션 사이는 (빈 줄) ⸻⸻⸻⸻ (빈 줄)
        body, seen_section = [], False
        for ln in lines[i:]:
            s = ln.strip()
            if not s or _SEP_CHARS_RE.match(s):
                continue                      # 간격은 전부 재계산
            if SECTION_HEADER_RE.match(s):
                if seen_section:
                    body += ['', sep, '']
                seen_section = True
                body.append(ln)
                body.append('')               # 헤더 다음 빈 줄 1개
                continue
            # 항목 줄 — 정치 브리핑 구식 '-' 불릿은 ▪ 로 통일
            if s.startswith('- '):
                ln = ln.replace('- ', '▪ ', 1)
            elif s == '-':
                continue
            body.append(ln)

        body = fill_empty_general_sections(body)

        out = title + ['']
        out += cfg['header_lines'] + ['']
        out += body
        out += [''] + cfg['footer_lines']
        return '\n'.join(out)
    except Exception as e:
        logger.error(f'[레이아웃] 적용 실패 — 원문 발송: {e}')
        return text
