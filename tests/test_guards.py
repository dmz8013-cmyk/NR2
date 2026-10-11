"""섹션 배치 검증 + 헤드라인 프레임 귀속 테스트. 실행: python3 tests/test_guards.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from section_guard import enforce_sections, load_party_map, party_of_title, is_party_politician, first_subject
from headline_guard import unattributed_frames, strip_frames, fix_headline, apply_to_briefing, load_frame_words

B = ("🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(261011 13:00)】🔥\n"
     "{headline}\n\n⸻⸻⸻⸻\n\n🇰🇷 이재명 정부 🇰🇷\n\n▪ 정동영 통일부 장관이 대북 정책을 설명했음.\n\n⸻⸻⸻⸻\n\n"
     "🟦 더불어민주당 🟦\n\n▪ 박성준 수석대변인이 국감 대응을 밝혔음.\n\n⸻⸻⸻⸻\n\n"
     "🟥 국민의힘 🟥\n\n▪ 한동훈 의원이 당 지도부를 비판했음.\n▪ 주호영 의원이 병역법 개정안을 대표발의했음.\n\n⸻⸻⸻⸻\n\n"
     "🎸 비교섭단체 및 기타 정치 🪕\n\n▪ 김용민 의원이 검찰개혁 후속 입법을 촉구했음.\n▪ 이준석 대표가 당 혁신안을 발표했음.\n\n⸻⸻⸻⸻\n\n"
     "🌐 법조 및 국제 🌐\n\n▪ 조희대 대법원장이 국감에 출석했음.")

def test_party_map():
    pm = load_party_map()
    assert pm["김용민"] == "더불어민주당" and pm["주호영"] == "국민의힘" and pm["한동훈"] == "비교섭단체" and pm["이준석"] == "비교섭단체"
    assert "정동영" not in pm and "조희대" not in pm           # 정부·사법 직책은 당적 대조 대상 아님
    assert party_of_title("무소속 국회의원 (외교통일위원회) — '국민의힘 대표' 표기는 오류") == "기타"
    assert not is_party_politician("문화체육관광부 장관")

def test_enforce_sections_moves_and_keeps():
    text = B.format(headline="제목")
    out, moved, dropped = enforce_sections(text)
    assert len(moved) == 2 and dropped == []
    assert any(m.startswith("김용민") and "더불어민주당" in m for m in moved)
    assert any(m.startswith("한동훈") and "비교섭단체" in m for m in moved)
    lines = out.split("\n")
    i_dem = next(i for i, l in enumerate(lines) if l.startswith("🟦")); i_ppp = next(i for i, l in enumerate(lines) if l.startswith("🟥"))
    i_min = next(i for i, l in enumerate(lines) if l.startswith("🎸")); i_law = next(i for i, l in enumerate(lines) if l.startswith("🌐"))
    i_kym = next(i for i, l in enumerate(lines) if "김용민" in l); i_hdh = next(i for i, l in enumerate(lines) if "한동훈" in l)
    assert i_dem < i_kym < i_ppp and i_min < i_hdh < i_law
    assert "주호영" in "\n".join(lines[i_ppp:i_min]) and "조희대" in "\n".join(lines[i_law:])

def test_enforce_sections_drop_when_no_target():
    text = "🟥 국민의힘 🟥\n\n▪ 김용민 의원이 발언했음.\n▪ 주호영 의원이 발의했음."
    out, moved, dropped = enforce_sections(text)
    assert moved == [] and len(dropped) == 1 and "김용민" not in out and "주호영" in out

def test_no_political_sections_untouched():
    g = "🏛️ 정치/시사\n\n▪ 김용민 의원이 발언했음."
    assert enforce_sections(g) == (g, [], [])

def test_headline_frames():
    fw = load_frame_words()
    assert "참사" in fw and "방탄" in fw
    assert unattributed_frames("이재명 정부 3대 참사…지지율 추락", fw) == ["참사"]
    assert unattributed_frames("국힘 정점식 '3대 참사' 공세…지지율 추락", fw) == []
    assert unattributed_frames("'방탄' 논란 재점화", fw) == ["방탄"]          # 따옴표만 있고 주체 없음
    assert strip_frames("이재명 정부 3대 참사…지지율 추락", ["참사"]) == "이재명 정부 3대…지지율 추락"
    assert strip_frames("여당 폭주에 야당 반발…검찰개혁 공방", ["폭주"]) == "여당 야당 반발…검찰개혁 공방"

def test_fix_headline_without_client_strips():
    new, info = fix_headline("여당 폭주에 야당 반발…검찰개혁 공방", None)
    assert "폭주" not in new and info["stripped"] and info["words"] == ["폭주"]
    text = B.format(headline="방탄 국회 재연…여야 충돌")
    out, info = apply_to_briefing(text, None)
    assert "방탄" not in out.split("\n")[1] and info["stripped"]

def test_fix_headline_with_fake_client():
    class R: pass
    class Client:
        class messages:
            @staticmethod
            def create(**kw):
                r = R(); c = R(); c.text = "국힘 정점식 '3대 참사' 공세…지지율 추락"; r.content = [c]; return r
    new, info = fix_headline("이재명 정부 3대 참사…지지율 추락", "▪ 정점식 원내대표가 '3대 참사'라고 공세", Client())
    assert new.startswith("국힘 정점식") and info["attempts"] == 1 and not info["stripped"]

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
