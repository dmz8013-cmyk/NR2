"""인터내셔널 시그널 텍스트 카드 레이아웃 테스트 (config/signal_layout.json).

실행: python -m pytest tests/test_signal_layout.py -v  (또는 python3 tests/test_signal_layout.py)
검증: 제목 · 부제/상단 정보방 블록 부재 · ━ 구분선 정확히 2개 · 항목 사이 빈 줄 1개
      · 하단 순서(구분선→원문 링크→카톡→텔레) · 4096 한도 · 항목 경계 분할.
"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('anthropic', 'requests', 'psycopg2'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

from leader_watch import build_text_card, split_card, load_signal_layout, SEP

DATE = "2026-09-17"


def _items(n, summary_len=0):
    out = []
    for i in range(n):
        summ = f"항목 {i} 요약문입니다." + ("가" * summary_len)
        out.append({"handle": f"user{i}", "name": f"인물{i}", "tier": 1,
                    "post_url": f"https://x.com/user{i}/status/12345678{i}",
                    "summary_ko": summ, "score": 8})
    return out


def _card(n=6, summary_len=0):
    return build_text_card(_items(n, summary_len), DATE)


def test_layout_config_loads():
    lay = load_signal_layout()
    assert lay["separator"] == "━" * 16
    assert "인터내셔널 시그널" in lay["title_format"]


def test_title_and_no_tagline():
    lines = _card().split("\n")
    assert lines[0] == "📡 인터내셔널 시그널 | 09/17"
    assert "누렁이 시그널" not in _card()
    assert "세계를 움직이는 150인" not in _card()


def test_exactly_two_separators_and_no_top_cta():
    card = _card()
    lines = card.split("\n")
    seps = [i for i, ln in enumerate(lines) if ln == SEP]
    assert len(seps) == 2, lines
    first_item = next(i for i, ln in enumerate(lines) if ln.startswith("▪"))
    last_item = max(i for i, ln in enumerate(lines) if ln.startswith("▪"))
    assert seps[0] < first_item and seps[1] > last_item
    # 상단(첫 구분선 이전)에는 정보방 링크 없음
    top = "\n".join(lines[:seps[0]])
    assert "buly.kr" not in top and "t.me/" not in top
    # 구분선은 ━ 16개만 — 다른 종류(─, ⸻) 없음
    assert "─" not in card and "⸻" not in card


def test_blank_line_between_items_internal_newline_kept():
    items = _items(3)
    items[1]["summary_ko"] = "첫 줄\n둘째 줄"
    lines = build_text_card(items, DATE).split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.startswith("▪")]
    assert len(idx) == 3
    # 항목0 → 빈 줄 → 항목1(2줄) → 빈 줄 → 항목2
    assert lines[idx[0] + 1] == "" and lines[idx[0] + 2] == lines[idx[1]]
    assert lines[idx[1] + 1] == "둘째 줄"
    assert lines[idx[1] + 2] == "" and lines[idx[1] + 3] == lines[idx[2]]


def test_footer_order():
    lines = [ln for ln in _card().split("\n") if ln]   # 빈 줄 제외
    tail = lines[-4:]
    assert tail[0] == SEP
    assert tail[1] == f"원문 링크·전체 보기 → nr2.kr/signal/{DATE}"
    assert tail[2].startswith("누렁이 정보방(카카오톡) https://")
    assert tail[3].startswith("누렁이 정보방(텔레그램) https://")


def test_within_telegram_limit_at_max_items():
    # 8개 × 요약 300자 — 실제 상한을 넉넉히 넘는 가정에서도 단일 청크
    card = _card(8, summary_len=300)
    assert len(card) < 4000
    assert split_card(card) == [card]


def test_split_at_item_boundary():
    card = _card(8, summary_len=900)          # 강제로 한도 초과
    chunks = split_card(card, limit=4000)
    assert len(chunks) >= 2
    assert "\n".join(chunks).replace("\n\n", "\n") == card.replace("\n\n", "\n")
    for c in chunks:
        assert len(c) <= 4000
        assert not c.startswith("\n") and not c.endswith("\n")
    # 각 청크 경계 = 항목 경계: 청크는 항목/헤더 줄로 시작, 항목이 잘리지 않음
    for c in chunks[1:]:
        assert c.startswith("▪") or c.startswith(SEP) or c == "" , c[:40]


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
