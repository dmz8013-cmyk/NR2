"""
g2b_review.py — 검수 부담 축소 도구 (기계 선처리)

1) rejudge_ambiguous(): '애매' 판정 전건을 엄격 기준으로 Haiku 재판정
   - 핵심 질문: AI가 사업의 핵심 수단인가 / 단순 언급·교육 대상·장비 구매인가
   - 예/아니오로 해소된 건은 DB 갱신, 그래도 애매한 것만 잔존
2) automap_unmapped(): 매핑 미제(공사공단·교육청) 기관명을 웹검색으로
   소속 지자체 자동 판정 — 확신 '상'만 DB 반영, 중·하는 잔존
3) export_residuals(): 잔여 검수 CSV 재생성

사용: python g2b_review.py [--rejudge] [--automap] [--export]  (기본: 전부)
환경: ANTHROPIC_API_KEY, DATABASE_URL 필요. 실패 건은 스킵+로그.
"""

import os
import csv
import json
import logging
import sys

from g2b_tracker import db_conn, _load_mapping

try:
    import anthropic
except ImportError:
    anthropic = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("g2b_review")

MODEL = "claude-haiku-4-5-20251001"

STRICT_PROMPT = """다음 공공 입찰공고를 'AI 기술이 사업의 핵심 수단인가' 기준으로 엄격하게 재판정하라.

공고명: {bid_name}
수요기관: {org_name}

[예] AI 시스템·모델·챗봇·플랫폼·알고리즘의 구축/개발/고도화/운영/유지관리/감리가 과업의 중심
[아니오] 아래는 전부 아니오로 판정:
 - 'AI시대', 'AI 역량' 등 단순 언급·수식어에 그치는 경우
 - AI가 교육·연수·강의의 '대상'인 경우 (AI 교육과정 운영, AI 체험 행사 등)
 - 기성품·장비 구매 (지능형CCTV, AI스피커, 로봇청소기, 키오스크 등 하드웨어 조달)
 - 행사·홍보·일반 컨설팅에 AI가 부수적으로 붙은 경우
[애매] 위 구분이 공고명·기관명만으로 정말 불가능한 경우에만 (최후 수단으로 최소화)

반드시 JSON 만: {{"verdict":"예" 또는 "아니오" 또는 "애매", "reason":"근거 1문장"}}"""

AUTOMAP_PROMPT = """다음 한국 공공기관의 소속(관할) 지자체를 판정하라. 필요하면 검색하라.

기관명: {org_name}
기관유형: {org_tag}

허용되는 지자체 표기 (반드시 이 중 하나로만):
- 광역: {metros}
- 기초: "광역 기초" 형식 (예: "경기 구리시", "서울 강남구", "광주전남 나주시")
※ 광주광역시·전라남도 소속은 모두 "광주전남" 으로 표기.
※ 중앙정부·국가공기업(한국전력 등)·민간이면 gov_name 을 "해당없음" 으로.

반드시 JSON 만:
{{"gov_level":"광역" 또는 "기초" 또는 "해당없음",
 "gov_name":"위 표기 그대로",
 "confidence":"상" 또는 "중" 또는 "하",
 "reason":"근거 1문장"}}"""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or anthropic is None:
        raise EnvironmentError("ANTHROPIC_API_KEY 필요")
    return anthropic.Anthropic(api_key=key, timeout=60.0)


def _json_of(text: str) -> dict:
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1])


def _valid_gov_names() -> tuple[set, set]:
    m = _load_mapping()
    metros = set(m["광역"].keys())
    basics = {f"{a} {b}" for a, bl in m["기초"].items() for b in bl}
    return metros, basics


# ══════════════════════════════════════════════════
#  1. 애매 재판정 (엄격 기준)
# ══════════════════════════════════════════════════
def rejudge_ambiguous() -> dict:
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""SELECT bid_no, bid_name, org_name FROM ai_projects
                   WHERE ai_verdict='애매' AND is_latest ORDER BY bid_no""")
    targets = cur.fetchall()
    conn.close()
    logger.info(f"[재판정] 대상 {len(targets)}건")

    client = _client()
    stats = {"total": len(targets), "예": 0, "아니오": 0, "애매": 0, "오류": 0}
    for i, (bid_no, bid_name, org_name) in enumerate(targets, 1):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=200,
                messages=[{"role": "user", "content": STRICT_PROMPT.format(
                    bid_name=bid_name, org_name=org_name or "미상")}])
            data = _json_of(resp.content[0].text)
            v = data.get("verdict", "애매")
            if v not in ("예", "아니오", "애매"):
                v = "애매"
            reason = "[엄격재판정] " + (data.get("reason") or "")[:250]
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("UPDATE ai_projects SET ai_verdict=%s, ai_reason=%s WHERE bid_no=%s",
                        (v, reason, bid_no))
            conn.commit()
            conn.close()
            stats[v] += 1
        except Exception as e:
            stats["오류"] += 1
            logger.warning(f"[재판정] 실패 스킵({bid_no}): {e}")
        if i % 50 == 0:
            logger.info(f"[재판정] {i}/{len(targets)} — {stats}")
    logger.info(f"[재판정] 완료: {stats}")
    return stats


# ══════════════════════════════════════════════════
#  2. 매핑 미제 자동 매핑 (웹검색)
# ══════════════════════════════════════════════════
def automap_unmapped() -> dict:
    metros, basics = _valid_gov_names()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT org_name, org_tag FROM ai_projects
                   WHERE is_latest AND gov_name='미분류'
                     AND org_tag IN ('공사공단','교육청') ORDER BY org_name""")
    orgs = cur.fetchall()
    conn.close()
    logger.info(f"[자동매핑] 고유 기관 {len(orgs)}곳")

    client = _client()
    stats = {"orgs": len(orgs), "mapped": 0, "low_conf": 0, "na": 0, "오류": 0, "rows": 0}
    for i, (org_name, org_tag) in enumerate(orgs, 1):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=300,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
                messages=[{"role": "user", "content": AUTOMAP_PROMPT.format(
                    org_name=org_name, org_tag=org_tag,
                    metros=", ".join(sorted(metros)))}])
            final = ""
            for b in resp.content:
                if getattr(b, "type", "") == "text":
                    final = b.text
            data = _json_of(final)
            lvl, gov = data.get("gov_level"), (data.get("gov_name") or "").strip()
            conf = data.get("confidence")
            # 어휘 검증: 매핑 표기 밖이면 반영 안 함
            ok = (lvl == "광역" and gov in metros) or (lvl == "기초" and gov in basics)
            if lvl == "해당없음":
                stats["na"] += 1
                continue
            if conf == "상" and ok:
                conn = db_conn()
                cur = conn.cursor()
                cur.execute("""UPDATE ai_projects SET gov_level=%s, gov_name=%s
                               WHERE org_name=%s AND gov_name='미분류'""",
                            (lvl, gov, org_name))
                stats["rows"] += cur.rowcount
                conn.commit()
                conn.close()
                stats["mapped"] += 1
                logger.info(f"[자동매핑] {org_name} → {gov} ({cur.rowcount}행)")
            else:
                stats["low_conf"] += 1
        except Exception as e:
            stats["오류"] += 1
            logger.warning(f"[자동매핑] 실패 스킵({org_name}): {e}")
        if i % 25 == 0:
            logger.info(f"[자동매핑] {i}/{len(orgs)} — {stats}")
    logger.info(f"[자동매핑] 완료: {stats}")
    return stats


# ══════════════════════════════════════════════════
#  3. 잔여 검수 CSV
# ══════════════════════════════════════════════════
def export_residuals(out_dir: str = "/tmp") -> tuple[str, str, int, int]:
    conn = db_conn()
    cur = conn.cursor()

    p1 = os.path.join(out_dir, "review_ambiguous_v2.csv")
    cur.execute("""SELECT bid_no, bid_name, org_name, gov_name, est_price, notice_date,
                          src_type, ai_reason
                   FROM ai_projects WHERE ai_verdict='애매' AND is_latest
                   ORDER BY COALESCE(est_price,0) DESC""")
    rows = cur.fetchall()
    with open(p1, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["공고번호", "공고명", "수요기관", "지자체매핑", "추정가격", "공고일",
                    "업무구분", "판정근거", "검수결과(예/아니오 기입)"])
        for r in rows:
            w.writerow(list(r) + [""])
    n1 = len(rows)

    p2 = os.path.join(out_dir, "review_unmapped_v2.csv")
    cur.execute("""SELECT bid_no, bid_name, org_name, org_tag, ai_verdict, est_price, notice_date
                   FROM ai_projects
                   WHERE is_latest AND gov_name='미분류' AND org_tag IN ('공사공단','교육청')
                   ORDER BY org_tag, org_name""")
    rows = cur.fetchall()
    with open(p2, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["공고번호", "공고명", "수요기관", "기관태그", "AI판정", "추정가격",
                    "공고일", "소속지자체(기입)"])
        for r in rows:
            w.writerow(list(r) + [""])
    n2 = len(rows)
    conn.close()
    logger.info(f"[잔여CSV] 애매 {n1}건 → {p1} / 매핑미제 {n2}건 → {p2}")
    return p1, p2, n1, n2


if __name__ == "__main__":
    args = sys.argv[1:]
    do_all = not args
    results = {}
    if do_all or "--rejudge" in args:
        results["rejudge"] = rejudge_ambiguous()
    if do_all or "--automap" in args:
        results["automap"] = automap_unmapped()
    if do_all or "--export" in args:
        p1, p2, n1, n2 = export_residuals()
        results["residuals"] = {"ambiguous": n1, "unmapped": n2}
    print(json.dumps(results, ensure_ascii=False, indent=2))
