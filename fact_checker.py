"""
fact_checker.py — 브리핑 팩트체크 모듈

브리핑 텍스트에서 인물-직책 오류를 자동 감지·수정한다.
fact_sheet.json을 참조하여 현직/전직 혼동을 방지.

사용법:
  from fact_checker import run_fact_check, auto_fix

  result = run_fact_check(text)
  if not result["passed"]:
      text = auto_fix(text)

CLI:
  python fact_checker.py check  --text "이준석 대통령이 ..."
  python fact_checker.py update --field president.current --value "새이름"
  python fact_checker.py test
"""

import json
import logging
import os
import re
import sys
from datetime import datetime

logger = logging.getLogger("fact_checker")

# ── fact_sheet.json 경로 ──
FACT_SHEET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fact_sheet.json")


def _load_fact_sheet() -> dict:
    """fact_sheet.json 로드"""
    with open(FACT_SHEET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_fact_sheet(data: dict):
    """fact_sheet.json 저장"""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(FACT_SHEET_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"fact_sheet.json 업데이트 완료 ({data['last_updated']})")


# ══════════════════════════════════════════════════
#  1. check_president — 대통령 이름 검증
# ══════════════════════════════════════════════════
def check_president(text: str) -> dict:
    """
    텍스트에서 "X 대통령" 패턴을 찾아 올바른 이름인지 검증.
    잘못된 이름이 대통령으로 지칭되면 오류 반환.
    """
    sheet = _load_fact_sheet()
    president = sheet["president"]
    current = president["current"]
    wrong_names = president["wrong_names"]

    # "이름 + 대통령" 패턴 (단, "전 대통령", "전직 대통령" 제외)
    pattern = re.compile(
        r"(?P<name>\w{2,4})\s*(?:현\s*)?대통령(?!\s*권한대행)",
    )

    for match in pattern.finditer(text):
        name = match.group("name")

        # "전 대통령", "전직 대통령" 패턴이면 건너뛰기
        start = max(0, match.start() - 5)
        prefix = text[start : match.start()]
        if re.search(r"전\s*$|전직\s*$|파면된\s*$|탄핵된\s*$", prefix):
            continue

        if name in wrong_names:
            # 해당 인물의 올바른 직책 찾기
            correct_title = current + " 대통령"
            for fig in sheet.get("key_figures", []):
                if fig["name"] == name:
                    correct_title = f"{name} {fig['correct_title']}"
                    break

            context_start = max(0, match.start() - 20)
            context_end = min(len(text), match.end() + 20)
            context = text[context_start:context_end]

            return {
                "error": True,
                "found": name,
                "should_be": current,
                "correct_title": correct_title,
                "context": context,
            }

    return {"error": False}


# ══════════════════════════════════════════════════
#  2. check_all_titles — 전체 인물 직책 검증
# ══════════════════════════════════════════════════
def check_all_titles(text: str) -> list:
    """
    key_figures를 순회하며 "이름 + 잘못된직책" 패턴 감지.
    """
    sheet = _load_fact_sheet()
    errors = []

    for figure in sheet.get("key_figures", []):
        name = figure["name"]
        correct = figure["correct_title"]
        wrong_titles = figure["wrong_titles"]

        for wrong in wrong_titles:
            # "이름 + 잘못된직책" 패턴 (단, "전" 접두어 제외)
            pattern = re.compile(
                rf"(?<!전\s)(?<!전직\s)(?<!파면된\s){re.escape(name)}\s*{re.escape(wrong)}"
            )
            for match in pattern.finditer(text):
                # "전 대통령" 같은 접두어 이중 확인
                start = max(0, match.start() - 5)
                prefix = text[start : match.start()]
                if re.search(r"전\s*$|전직\s*$|파면된\s*$|탄핵된\s*$", prefix):
                    continue

                context_start = max(0, match.start() - 20)
                context_end = min(len(text), match.end() + 20)

                errors.append({
                    "type": "wrong_title",
                    "found": f"{name} {wrong}",
                    "should_be": f"{name} {correct}",
                    "context": text[context_start:context_end],
                })

    return errors


# ══════════════════════════════════════════════════
#  3. run_fact_check — 통합 팩트체크
# ══════════════════════════════════════════════════
def run_fact_check(text: str) -> dict:
    """
    check_president + check_all_titles 통합 실행.
    반환: {"passed": bool, "errors": list, "warnings": list, "checked_at": str}
    """
    errors = []
    warnings = []

    # 대통령 이름 검증
    pres_result = check_president(text)
    if pres_result["error"]:
        errors.append({
            "type": "wrong_president",
            "found": pres_result["found"],
            "should_be": pres_result["should_be"],
            "correct_title": pres_result.get("correct_title", ""),
            "context": pres_result["context"],
        })

    # 전체 인물 직책 검증
    title_errors = check_all_titles(text)
    errors.extend(title_errors)

    # 경고: "대통령" 단어가 있지만 이름이 없는 경우
    if "대통령" in text and not re.search(r"\w{2,4}\s*대통령", text):
        warnings.append({
            "type": "unnamed_president",
            "message": "'대통령' 언급이 있으나 이름이 명시되지 않음",
        })

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checked_at": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════
#  4. auto_fix — 자동 수정
# ══════════════════════════════════════════════════
def auto_fix(text: str) -> str:
    """
    오류 발견 시 자동으로 텍스트 수정.
    수정된 부분은 로그에 기록.
    """
    sheet = _load_fact_sheet()
    fixed = text

    for figure in sheet.get("key_figures", []):
        name = figure["name"]
        correct = figure["correct_title"]
        # correct_title에서 첫 번째 슬래시 앞의 직책만 사용
        short_title = correct.split("/")[0].strip()
        wrong_titles = figure["wrong_titles"]

        for wrong in wrong_titles:
            # "전 X" 패턴은 건너뛰기 위해 negative lookbehind 사용
            pattern = re.compile(
                rf"(?<!전\s)(?<!전직\s)(?<!파면된\s)({re.escape(name)})\s*({re.escape(wrong)})"
            )

            def _replacer(m):
                original = m.group(0)
                # 앞 5글자 확인하여 "전" 접두어 이중 확인
                start = max(0, m.start() - 5)
                prefix = fixed[start : m.start()]
                if re.search(r"전\s*$|전직\s*$|파면된\s*$|탄핵된\s*$", prefix):
                    return original

                replacement = f"{name} {short_title}"
                logger.warning(f"[팩트 자동수정] '{original}' → '{replacement}'")
                return replacement

            fixed = pattern.sub(_replacer, fixed)

    return fixed


# ══════════════════════════════════════════════════
#  5. 프롬프트용 팩트 컨텍스트 생성
# ══════════════════════════════════════════════════
def get_fact_context() -> str:
    """브리핑 생성 프롬프트 앞에 주입할 고정 팩트 컨텍스트 반환."""
    sheet = _load_fact_sheet()
    pres = sheet["president"]
    pm = sheet["prime_minister"]

    lines = [
        "\n[필수 고정 팩트 — 이 내용과 다른 표현은 절대 사용 금지]",
        f"- 현 대한민국 대통령: {pres['current']} ({pres['order']}, {pres['term_start']} 취임)",
    ]

    for fig in sheet.get("key_figures", []):
        lines.append(f"- {fig['name']}: {fig['correct_title']}")

    if pm.get("current"):
        lines.append(f"- 현 국무총리: {pm['current']}")

    lines.append(
        "위 사실과 충돌하는 표현이 원문에 있어도 요약 시 반드시 위 팩트 기준으로 수정할 것.\n"
    )

    return "\n".join(lines)


# ══════════════════════════════════════════════════
#  6. CLI 인터페이스
# ══════════════════════════════════════════════════
def cli_update(field: str, value: str):
    """fact_sheet.json 필드 업데이트"""
    sheet = _load_fact_sheet()
    keys = field.split(".")
    target = sheet
    for k in keys[:-1]:
        target = target[k]
    old_value = target.get(keys[-1], "(없음)")
    target[keys[-1]] = value
    _save_fact_sheet(sheet)
    print(f"[UPDATE] {field}: '{old_value}' → '{value}'")


def cli_check(text: str):
    """텍스트 팩트체크"""
    result = run_fact_check(text)
    print(f"입력: {text}")
    if result["passed"]:
        print("결과: ✅ 통과")
    else:
        print("결과: ❌ 오류 감지")
        for err in result["errors"]:
            print(f"  - '{err['found']}' → '{err['should_be']}'")
            print(f"    문맥: {err['context']}")
        fixed = auto_fix(text)
        print(f"자동수정: {fixed}")

    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  ⚠️ {w['message']}")


def cli_test():
    """샘플 테스트"""
    test_cases = [
        "이준석 대통령이 고용 유연성 발언을 했다",
        "이재명 대통령이 국무회의를 주재했다",
        "윤석열 대통령은 오늘 외교 일정을 소화했다",
        "이준석 개혁신당 대표가 기자회견을 열었다",
        "윤석열 전 대통령이 법정에 출석했다",
        "한덕수 대통령이 국무회의를 주재했다",
    ]

    print("=" * 60)
    print("팩트체커 테스트")
    print("=" * 60)

    for text in test_cases:
        result = run_fact_check(text)
        status = "✅ 통과" if result["passed"] else "❌ 오류 감지"
        print(f"\n입력: {text}")
        print(f"결과: {status}")
        if not result["passed"]:
            fixed = auto_fix(text)
            print(f"수정: {fixed}")
            for err in result["errors"]:
                print(f"  → '{err['found']}' → '{err['should_be']}'")

    print("\n" + "=" * 60)
    print("프롬프트 팩트 컨텍스트:")
    print(get_fact_context())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print("사용법:")
        print("  python fact_checker.py test")
        print("  python fact_checker.py check  --text '브리핑 텍스트'")
        print("  python fact_checker.py update --field president.current --value '새이름'")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "test":
        cli_test()
    elif cmd == "check":
        if "--text" in sys.argv:
            idx = sys.argv.index("--text")
            text = sys.argv[idx + 1]
        else:
            text = " ".join(sys.argv[2:])
        cli_check(text)
    elif cmd == "update":
        field = sys.argv[sys.argv.index("--field") + 1]
        value = sys.argv[sys.argv.index("--value") + 1]
        cli_update(field, value)
    else:
        print(f"알 수 없는 명령: {cmd}")
        sys.exit(1)
