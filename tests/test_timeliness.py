"""시의성 필터 테스트. 실행: python3 tests/test_timeliness.py"""
import sys, os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from timeliness import filter_timely, allowed_dates, to_kst, format_exclusions
KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 7, 13, 0, tzinfo=KST)

def _run(arts, **kw):
    return filter_timely(arts, now=NOW, fetcher=kw.pop("fetcher", lambda u: None), **kw)

def test_allowed_dates():
    assert {d.isoformat() for d in allowed_dates(NOW)} == {"2026-10-07", "2026-10-06"}

def test_yesterday_2359_passes():
    p, e = _run([{"title": "a", "pub_date": datetime(2026, 10, 6, 23, 59, tzinfo=KST)}])
    assert len(p) == 1 and e == [] and p[0]["pub_label"] == "10/06 23:59"

def test_two_days_ago_0001_excluded():
    p, e = _run([{"title": "b", "published": "2026-10-05T00:01:00+09:00"}])
    assert p == [] and e[0]["reason"].startswith("발행일 10/05")

def test_missing_pubdate_excluded_without_html():
    p, e = _run([{"title": "c", "link": "https://x.test/1"}])
    assert p == [] and e[0]["reason"] == "발행시각 없음"

def test_missing_pubdate_html_fallback():
    fetched = []
    def fk(u): fetched.append(u); return datetime(2026, 10, 7, 9, 0, tzinfo=KST)
    p, e = _run([{"title": "d", "link": "https://x.test/2"}], fetcher=fk)
    assert len(p) == 1 and fetched == ["https://x.test/2"] and p[0]["published"].startswith("2026-10-07")

def test_html_budget():
    calls = []
    def fk(u): calls.append(u); return None
    arts = [{"title": str(i), "link": f"https://x.test/{i}"} for i in range(5)]
    p, e = _run(arts, fetcher=fk, html_budget=2)
    assert len(calls) == 2 and len(e) == 5

def test_utc_pubdate_kst_boundary():
    # 기준 10/06 13:00 KST. UTC 10/05 15:30 = KST 10/06 00:30 → 당일 → 통과 / UTC 10/05 14:30 = KST 10/05 23:30 → 전일이지만 날짜 경계 확인용
    now = datetime(2026, 10, 6, 1, 0, tzinfo=KST)
    p, e = filter_timely([{"title": "e", "pub_date": "Mon, 05 Oct 2026 15:30:00 +0000"},
                          {"title": "f", "pub_date": "Sun, 04 Oct 2026 14:30:00 +0000"}], now=now, fetcher=lambda u: None)
    assert [a["title"] for a in p] == ["e"] and [x["title"] for x in e] == ["f"]
    assert to_kst("2026-10-05T15:30:00Z").strftime("%m/%d %H:%M") == "10/06 00:30"

def test_cross_check_reindexed_pubdate():
    fk = lambda u: datetime(2026, 9, 18, 10, 0, tzinfo=KST)
    arts = [{"title": "재색인", "link": "https://x.test/old", "pub_date": datetime(2026, 10, 7, 11, 0, tzinfo=KST)}]
    p, e = _run(arts, fetcher=fk, cross_check=True)
    assert p == [] and "재색인 의심" in e[0]["reason"]
    p2, e2 = _run(arts, fetcher=fk)           # cross_check 없으면 pubDate 신뢰
    assert len(p2) == 1


def test_strict_switch():
    import timeliness as tl
    os.environ["TIMELINESS_STRICT"] = "0"
    try:
        p, e = _run([{"title": "g", "link": "https://x.test/9"}])
        assert len(p) == 1 and e == [] and p[0]["timeliness_lenient"] is True and p[0]["pub_label"] == "발행시각 없음"
        assert tl.format_lenient(tl.LAST_LENIENT).startswith("⚠️ 발행시각 없음 통과 1건")
        from timeline_filter import filter_articles
        kept = filter_articles(p, NOW, NOW, briefing_type="ai_morning")
        assert len(kept) == 1
    finally:
        os.environ["TIMELINESS_STRICT"] = "1"
    p, e = _run([{"title": "g", "link": "https://x.test/9"}])
    assert p == [] and len(e) == 1


def test_format_exclusions():
    _, e = _run([{"title": "오래된 기사 제목", "link": "https://news.example.co.kr/a", "published": "2026-09-18T10:00:00+09:00"}])
    line = format_exclusions(e)
    assert line.startswith("시의성 제외 1건:") and "09/18" in line and "news.example.co.kr" in line

def test_published_at_set_in_kst():
    p, _ = _run([{"title": "h", "pub_date": "Wed, 07 Oct 2026 02:00:00 +0000"}])
    assert p[0]["published_at"] == "2026-10-07T11:00:00+09:00"

def test_24h_boundary():
    p, e = _run([{"title": "in", "published": "2026-10-06T13:00:00+09:00"},
                 {"title": "out", "published": "2026-10-06T12:59:00+09:00"}])
    assert [a["title"] for a in p] == ["in"] and [x["title"] for x in e] == ["out"]

def test_undated_tagged_and_queued():
    import timeliness as tl, recheck_queue
    _, e = _run([{"title": "무날짜", "link": "https://x.test/u"}])
    assert e[0]["title"] == "[날짜미상] 무날짜" and e[0]["undated"] is True
    calls, orig = [], recheck_queue.enqueue_undated
    recheck_queue.enqueue_undated = lambda *a: calls.append(a) or 1
    try:
        assert tl.queue_undated(e + [{"title": "dated"}], "politics") == 1
    finally:
        recheck_queue.enqueue_undated = orig
    assert calls[0][:2] == ("politics", "[날짜미상] 무날짜")

def test_cross_check_reindexed_within_yesterday():
    fk = lambda u: datetime(2026, 10, 6, 9, 0, tzinfo=KST)     # 28h 전 = 전일이지만 24h 초과
    arts = [{"title": "재색인", "link": "https://x.test/y", "pub_date": datetime(2026, 10, 7, 11, 0, tzinfo=KST)}]
    p, e = _run(arts, fetcher=fk, cross_check=True)
    assert p == [] and "재색인 의심" in e[0]["reason"]

def test_prompts_have_date_rule():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import publish_guard
    assert "[날짜 표현]" in publish_guard.prompt_rules("11/09")
    for f in ("ai_briefing.py", "political_briefing.py"):
        assert "{pg_rules}" in open(os.path.join(root, f), encoding="utf8").read()


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
