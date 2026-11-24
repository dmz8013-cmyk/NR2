"""url_dedup.py — API 호출 전 URL 중복 제거 공용 함수 (2026-11-24).

같은 기사가 추적 파라미터(utm_*, fbclid 등)·fragment·끝 슬래시·http/https 차이로
다른 URL 처럼 보여 두 번 채점·분석되는 것을 막는다.
"""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref_src", "cmpid", "smid"}


def normalize(url: str) -> str:
    """비교용 정규형. 원본 URL 은 그대로 저장·발송하고 비교에만 쓴다."""
    if not url:
        return ""
    try:
        u = urlsplit(url.strip())
        host = (u.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if u.port and u.port not in (80, 443):
            host = f"{host}:{u.port}"
        q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith(_TRACKING_PREFIXES) and k not in _TRACKING_KEYS]
        path = u.path.rstrip("/") or "/"
        return urlunsplit(("https", host, path, urlencode(sorted(q)), ""))
    except Exception:
        return url.strip()


def unique(items: list, key: str = "link", seen: set | None = None) -> tuple[list, int]:
    """URL 기준 첫 항목만 남김. → (남은 목록, 제거 건수). URL 이 없는 항목은 그대로 둔다.
    seen 을 넘기면 여러 목록에 걸쳐 누적 판정한다(호출 측에서 같은 set 재사용)."""
    seen = set() if seen is None else seen
    out, dropped = [], 0
    for it in items:
        u = it.get(key) if isinstance(it, dict) else None
        n = normalize(u) if u else ""
        if n and n in seen:
            dropped += 1
            continue
        if n:
            seen.add(n)
        out.append(it)
    return out, dropped
