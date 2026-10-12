"""5차(13:00판 빈 섹션) 테스트 — 섹션 채움·속보·반박·출처 매칭·상한·문체·기보도 인용·24h·창. 실행: python3 tests/test_round5.py"""
import sys, os, types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("anthropic", "psycopg2", "feedparser", "requests", "pytz"):
    try: __import__(m)
    except ImportError: sys.modules[m] = types.ModuleType(m)
import section_fill as sf, style_fix, prior_coverage as pc
from timeliness import filter_timely
from timeline_filter import COVERAGE_WINDOWS, MAX_STALENESS_HOURS
from headline_guard import ensure_breaking_in_headline, unattributed_frames, load_frame_words
KST = ZoneInfo("Asia/Seoul")

B = ("🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(261012 13:00)】🔥\n이재명 골프엔 근무태세…민주당 이중잣대 논란\n\n⸻⸻⸻⸻\n\n"
     "🇰🇷 이재명 정부 🇰🇷\n\n▪ 리얼미터 조사 결과 국정수행 지지율 35.2%로 2주 연속 하락.\n▪ 한국연구재단 전면 혁신 촉구…연구자 단체 처우 개선 요구\n\n⸻⸻⸻⸻\n\n"
     "🟦 더불어민주당 🟦\n\n▪ 이재명 골프 관련 '대통령도 사람, 휴식 필요'…야당 공세에 근무 태세 유지 주장으로 맞받아침\n▪ 국감서 신현송 한은 총재에 레버리지 ETF 경고 미흡 지적\n\n⸻⸻⸻⸻\n\n"
     "🟥 국민의힘 🟥\n\n▪ 국민의힘, 골프장 체류 공세 강화…여야 이중잣대 논란 가열\n\n⸻⸻⸻⸻\n\n"
     "🎸 비교섭단체 및 기타 정치 🪕\n\n\n⸻⸻⸻⸻\n\n🌐 법조 및 국제 🌐\n\n")
POOL = [{"title": "합참 '북한, 동해상으로 탄도미사일 발사'…軍 경계 강화", "description": "합동참모본부는 12일 오전 북한이 탄도미사일을 발사했다고 밝혔다", "pub_date": datetime(2026, 10, 12, 9, 25, tzinfo=KST), "breaking": True},
        {"title": "조국혁신당, 검찰개혁 후속 입법 촉구…'공소청 인력 보강'", "description": "조국혁신당이 12일 국회에서 공소청 인력 보강을 촉구했다", "pub_date": datetime(2026, 10, 12, 10, 0, tzinfo=KST)},
        {"title": "리얼미터 국정수행 지지율 35.2%…2주 연속 하락", "description": "리얼미터 조사에서 지지율 35.2%", "pub_date": datetime(2026, 10, 12, 8, 0, tzinfo=KST)},
        {"title": "국감서 신현송 한은 총재 레버리지 ETF 경고 미흡 지적", "description": "국감 레버리지 ETF", "pub_date": datetime(2026, 10, 12, 11, 0, tzinfo=KST)},
        {"title": "국민의힘, 대통령 골프장 체류 공세…이중잣대 논란", "description": "국민의힘 골프 공세", "pub_date": datetime(2026, 10, 12, 10, 30, tzinfo=KST)},
        {"title": "민주당, 국민의힘 골프장 체류 공세에 '윤석열 황제골프와 비교는 억지' 반박", "description": "더불어민주당이 국민의힘 골프 공세에 반박", "pub_date": datetime(2026, 10, 12, 11, 30, tzinfo=KST)}]

class FakeClient:
    """섹션 채움·반박·문체 재작성 응답을 고정으로 돌려주는 가짜 클라이언트."""
    class messages:
        @staticmethod
        def create(**kw):
            prompt = kw["messages"][0]["content"]; r = types.SimpleNamespace(); c = types.SimpleNamespace()
            if "'비교섭단체' 섹션" in prompt: c.text = "▪ 조국혁신당, 검찰개혁 후속 입법으로 공소청 인력 보강 촉구"
            elif "'법조' 섹션" in prompt: c.text = "▪ 합참, 북한 동해상 탄도미사일 발사 발표…군 경계 태세 강화"
            elif "'국민의힘' 섹션" in prompt: c.text = "▪ 국민의힘, 민주당 반박에 재반박…골프 공세 지속"
            elif "'더불어민주당' 섹션" in prompt: c.text = "▪ 민주당, 윤석열 황제골프와 비교는 억지라고 반박"
            elif "최상위 속보" in prompt: c.text = "북한 탄도미사일 발사…골프 공방 속 안보 긴장"
            elif "명사형" in prompt: c.text = "리얼미터 조사 결과 국정수행 지지율 35.2%로 2주 연속 하락함."
            else: c.text = "NONE"
            r.content = [c]; return r

def test_parse_and_counts():
    s = sf.parse_sections(B)
    assert set(s) == set(sf.SECTIONS) and sf.section_counts(B) == {"이재명 정부": 2, "더불어민주당": 2, "국민의힘": 1, "비교섭단체": 0, "법조": 0}

def test_source_match_drops_unmatched():
    out, dropped = sf.source_match_guard(B, POOL)
    assert len(dropped) == 1 and dropped[0].startswith("한국연구재단") and "리얼미터" in out

def test_fill_empty_sections_with_client():
    out, notes = sf.fill_empty_sections(B, POOL, FakeClient())
    c = sf.section_counts(out)
    assert c["비교섭단체"] >= 1 and c["법조"] >= 1 and sf.NO_NEWS not in out
    assert any(n.startswith("채움:비교섭단체") for n in notes) and any(n.startswith("채움:법조") for n in notes)
    assert all(v >= 1 for v in c.values())

def test_fill_without_candidates_inserts_no_news():
    out, notes = sf.fill_empty_sections(B, [], None)
    assert out.count(sf.NO_NEWS) == 2 and all(n.startswith("보도없음") or n.startswith("유지") for n in notes)
    # 헤더만 있는 섹션은 없어야 함
    for k, sec in sf.parse_sections(out).items():
        assert sec["items"], k

def test_enforce_breaking_generates_and_tops():
    out, notes = sf.enforce_breaking(B, POOL, FakeClient())
    secs = sf.parse_sections(out)
    assert secs["법조"]["items"] and "미사일" in secs["법조"]["items"][0][1] and notes
    out2, notes2 = sf.enforce_breaking(out, POOL, FakeClient())        # 이미 반영 → 변화 없음
    assert sf.section_counts(out2)["법조"] == sf.section_counts(out)["법조"]

def test_rebuttal_added():
    # 🟥에만 골프 쟁점이 있고 🟦에는 없는 경우 → 풀의 민주당 반박 기사로 🟦 보강
    b2 = B.replace("▪ 이재명 골프 관련 '대통령도 사람, 휴식 필요'…야당 공세에 근무 태세 유지 주장으로 맞받아침\n", "")
    out, notes = sf.enforce_rebuttal(b2, POOL, FakeClient())
    assert notes and "반박 보강(더불어민주당)" in notes[0] and "억지" in out
    out2, notes2 = sf.enforce_rebuttal(B, POOL, FakeClient())      # 양쪽 모두 골프 쟁점 보유 → 보강 없음
    assert notes2 == []

def test_cap_sections():
    many = "🟦 더불어민주당 🟦\n\n" + "\n".join(f"▪ 항목 {i}" for i in range(7))
    out, notes = sf.cap_sections(many)
    assert sf.section_counts(out)["더불어민주당"] == 5 and len(notes) == 2

def test_style_fix():
    t = "▪ 리얼미터 조사 결과 지지율이 35.2%로 하락했다.\n▪ 국감에서 총재가 사과했음.\n▪ 야권이 반발한 것으로 알려졌다. 추가 공세가 이어질 것으로 전해짐."
    out, notes = style_fix.fix_style(t, None)
    lines = out.split("\n")
    assert lines[0].endswith("하락했음.") and lines[1].endswith("사과했음.") and len(lines) == 2 and any("삭제" in n for n in notes)
    out2, _ = style_fix.fix_style("▪ 리얼미터 조사 결과 국정수행 지지율 35.2%로 2주 연속 하락했다.", FakeClient())
    assert out2.endswith("하락함.")

def test_prior_quote_containment_and_two_editions():
    prior = [{"type": "political_evening", "created_at": datetime(2026, 10, 11, 22, 0), "text": "박지원 의원, 대통령 휴일 골프 논란에 \"대통령도 사람\"이라며 야권 비판 반박"}]
    new = "이재명 골프 관련 '대통령도 사람, 휴식 필요'…야당의 공세에 '근무 태세 유지' 주장으로 맞받아침"
    assert pc.shares_quote(new, prior[0]["text"]) and not pc.is_new_development(new, prior[0]["text"])
    out, ex, kept = pc.filter_prior_coverage("🟦 더불어민주당 🟦\n\n▪ " + new, prior)
    assert len(ex) == 1
    import inspect; src = inspect.getsource(pc.load_recent_items)
    assert "ORDER BY created_at DESC LIMIT 3" in src and "briefing_type" in src     # 직전 발행본 3개(정치+종합) 항상 포함

def test_timeliness_24h_cap_and_windows():
    now = datetime(2026, 10, 12, 13, 0, tzinfo=KST)
    arts = [{"title": "a", "pub_date": now - timedelta(hours=23)}, {"title": "b", "pub_date": datetime(2026, 10, 11, 10, 0, tzinfo=KST)}]
    p, e = filter_timely(arts, now=now, fetcher=lambda u: None)
    assert [x["title"] for x in p] == ["a"] and "24h 초과" in e[0]["reason"]
    assert COVERAGE_WINDOWS["political_afternoon"]["max_age_hours"] >= 17 and MAX_STALENESS_HOURS == 24

def test_headline_breaking_and_frames():
    assert "이중잣대" in load_frame_words() and unattributed_frames("민주당 이중잣대 논란 점화") == ["이중잣대"]
    out, note = ensure_breaking_in_headline(B, ["합참 '북한, 동해상으로 탄도미사일 발사'"], FakeClient())
    assert "미사일" in out.split("\n")[1] and note.startswith("속보 반영")
    out2, note2 = ensure_breaking_in_headline(B, ["합참 '북한, 동해상으로 탄도미사일 발사'"], None)
    assert note2.startswith("속보 미반영")

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
