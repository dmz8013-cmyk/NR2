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
    # UTC 10/05 15:30 = KST 10/06 00:30 → 전일 → 통과 / UTC 10/05 14:30 = KST 10/05 23:30 → 제외
    p, e = _run([{"title": "e", "pub_date": "Mon, 05 Oct 2026 15:30:00 +0000"},
                 {"title": "f", "pub_date": "Mon, 05 Oct 2026 14:30:00 +0000"}])
    assert [a["title"] for a in p] == ["e"] and [x["title"] for x in e] == ["f"]
    assert to_kst("2026-10-05T15:30:00Z").strftime("%m/%d %H:%M") == "10/06 00:30"

def test_cross_check_reindexed_pubdate():
    fk = lambda u: datetime(2026, 9, 18, 10, 0, tzinfo=KST)
    arts = [{"title": "재색인", "link": "https://x.test/old", "pub_date": datetime(2026, 10, 7, 11, 0, tzinfo=KST)}]
    p, e = _run(arts, fetcher=fk, cross_check=True)
    assert p == [] and "재색인 의심" in e[0]["reason"]
    p2, e2 = _run(arts, fetcher=fk)           # cross_check 없으면 pubDate 신뢰
    assert len(p2) == 1


def test_format_exclusions():
    _, e = _run([{"title": "오래된 기사 제목", "link": "https://news.example.co.kr/a", "published": "2026-09-18T10:00:00+09:00"}])
    line = format_exclusions(e)
    assert line.startswith("시의성 제외 1건:") and "09/18" in line and "news.example.co.kr" in line

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
