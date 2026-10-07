"""config/facts.json ↔ fact_sheet.json 인물→직함 정합성 (불일치 0건이어야 함). 실행: python3 tests/test_facts_consistency.py"""
import sys, os, json, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _head(title: str) -> str:
    t = re.split(r"\s[—(\[]|\s/\s", title, maxsplit=1)[0]
    return t.replace("국회의원", "의원").replace("특별자치시장", "시장").replace(" ", "")

def facts_diff():
    facts = json.load(open(os.path.join(ROOT, "config", "facts.json"), encoding="utf-8"))["인물_직함"]
    sheet = json.load(open(os.path.join(ROOT, "fact_sheet.json"), encoding="utf-8"))
    rows, mism = [], []
    for fig in sheet["key_figures"]:
        name = fig["name"]; a = fig["correct_title"]; b = facts.get(name)
        if b is None:
            rows.append((name, a, "(facts.json 없음)", "MISSING")); mism.append(name); continue
        ok = _head(a) in _head(b) or _head(b) in _head(a)
        rows.append((name, a, b.split(" (verified")[0][:50], "OK" if ok else "MISMATCH"))
        if not ok: mism.append(name)
    return rows, mism

def test_no_mismatch():
    rows, mism = facts_diff()
    assert mism == [], mism

def test_no_kimjiyong():
    for fn in ("config/facts.json", "fact_sheet.json", "config/fixed_facts.json"):
        assert "김지용" not in open(os.path.join(ROOT, fn), encoding="utf-8").read(), fn

def test_defense_minister_unfilled():
    facts = json.load(open(os.path.join(ROOT, "config", "facts.json"), encoding="utf-8"))
    sheet = json.load(open(os.path.join(ROOT, "fact_sheet.json"), encoding="utf-8"))
    assert facts["직책_미확인"]["국방부 장관"]["must_search"] is True and facts["직책_미확인"]["국방부 장관"]["name"] == ""
    assert sheet["unfilled_positions"]["국방부 장관"]["must_search"] is True
    from fact_checker import get_fact_context
    assert "국방부 장관: 현직자 성명 미확인" in get_fact_context()

if __name__ == "__main__":
    rows, mism = facts_diff()
    for r in rows: print(f"{r[3]:9s} {r[0]:5s} | sheet: {r[1][:28]:30s} | facts: {r[2]}")
    print(f"\n인물→직함 대조 {len(rows)}건 · 불일치 {len(mism)}건 {mism}")
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
    sys.exit(1 if fails or mism else 0)
