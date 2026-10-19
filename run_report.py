"""run_report.py — 브리핑 회차 요약 (관리자 DM 한 통).

'시의성 제외 N · 미확인→큐 M · 큐 복귀 K · 폐기 D' 요약 줄 + 세부 줄(시의성 제외 예시,
시의성 미달 제외, 존재 불명, 큐 적재/복귀/폐기 제목)을 한 메시지로 보낸다. 전송 실패는 로그만."""
import os
import logging

logger = logging.getLogger("run_report")


class RunReport:
    def __init__(self, briefing_type: str):
        self.briefing_type = briefing_type
        self.timeliness_excluded: list[dict] = []
        self.timeliness_lenient: list[dict] = []
        self.queued: list[str] = []
        self.restored: list[str] = []
        self.discarded: list[str] = []
        self.stale: list[str] = []
        self.unknown: list[str] = []
        self.unconfirmed_dropped: list[str] = []
        self.record_dropped: list[str] = []
        self.source_added: list[str] = []
        self.source_dropped: list[str] = []
        self.prior_excluded: list[str] = []
        self.prior_kept: list[str] = []
        self.name_fixes: list[str] = []
        self.tense_fixed: list[str] = []
        self.section_moved: list[str] = []
        self.section_dropped: list[str] = []
        self.headline_fixed: list[str] = []
        self.coin_dropped: list[str] = []
        self.coin_moved: list[str] = []
        self.prediction_dropped: list[str] = []
        self.sports_conflicts: list[str] = []
        self.source_dropped_items: list[str] = []
        self.breaking_notes: list[str] = []
        self.fill_notes: list[str] = []
        self.rebuttal_notes: list[str] = []
        self.style_notes: list[str] = []
        self.grounding_notes: list[str] = []      # 원문 대조 — 과장 동사·원문 밖 수치 (2026-10-19)
        self.age_dropped: list[dict] = []         # 24h 하드 필터 제거 기사
        self.section_counts: dict = {}
        self.calls = 0
        self.searches = 0
        self.extra: list[str] = []

    def summary_line(self) -> str:
        return (f"시의성 제외 {len(self.timeliness_excluded)} · 24h 초과 {len(self.age_dropped)} · "
                f"원문대조 교정 {len(self.grounding_notes)} · 기보도 제외 {len(self.prior_excluded)} · "
                f"기록·수치 삭제 {len(self.record_dropped) + len(self.source_dropped)} · "
                f"섹션 이동 {len(self.section_moved)} · 코인 정리 {len(self.coin_dropped) + len(self.coin_moved)} · "
                f"미확인→큐 {len(self.queued)} · 큐 복귀 {len(self.restored)} · 폐기 {len(self.discarded)}")

    def text(self) -> str:
        from timeliness import format_exclusions, format_lenient
        lines = [f"📋 <b>{self.briefing_type} 회차 요약</b>", self.summary_line(),
                 format_exclusions(self.timeliness_excluded)]
        if self.timeliness_lenient:
            lines.append(format_lenient(self.timeliness_lenient))
        lines += [f"시의성 미달 제외: {t}" for t in self.stale]
        lines += [f"존재 불명: {t}" for t in self.unknown]
        lines += [f"미확인→큐: {t}" for t in self.queued]
        lines += [f"큐 복귀: {t}" for t in self.restored]
        lines += [f"큐 폐기(2회 미확인): {t}" for t in self.discarded]
        lines += [f"미확인 제외: {t}" for t in self.unconfirmed_dropped]
        lines += [f"기록 미확인 삭제: {t}" for t in self.record_dropped]
        lines += [f"수치 삭제: {t}" for t in self.source_dropped]
        lines += [f"출처 병기: {t}" for t in self.source_added]
        lines += [f"기보도 제외: {t}" for t in self.prior_excluded]
        lines += [f"기보도·새 전개 유지: {t}" for t in self.prior_kept]
        lines += [f"구단명 교정: {t}" for t in self.name_fixes]
        lines += [f"시제 교정: {t}" for t in self.tense_fixed]
        lines += [f"섹션 이동: {t}" for t in self.section_moved]
        lines += [f"섹션 삭제(대상 없음): {t}" for t in self.section_dropped]
        lines += [f"제목 귀속: {t}" for t in self.headline_fixed]
        lines += [f"코인 상한 삭제: {t}" for t in self.coin_dropped]
        lines += [f"코인 💰 이동: {t}" for t in self.coin_moved]
        lines += [f"예측시장 삭제: {t}" for t in self.prediction_dropped]
        lines += [f"스포츠 주체: {t}" for t in self.sports_conflicts]
        if self.section_counts:
            lines.append("섹션 항목 수: " + " · ".join(f"{k} {v}" for k, v in self.section_counts.items()))
        lines += [f"출처 불명 삭제: {t}" for t in self.source_dropped_items]
        lines += [f"24h 초과 제거: {(d.get('title') or '')[:40]} ({d.get('age_hours')}h)" for d in self.age_dropped]
        lines += [f"원문대조: {t}" for t in self.grounding_notes]
        lines += [f"속보: {t}" for t in self.breaking_notes]
        lines += [f"섹션 채움: {t}" for t in self.fill_notes]
        lines += [f"반박 보강: {t}" for t in self.rebuttal_notes]
        if self.style_notes:
            lines.append(f"문체 교정 {len(self.style_notes)}건")
        lines += self.extra
        if self.calls or self.searches:
            lines.append(f"검증 호출 {self.calls}회 · 검색 {self.searches}회")
        return "\n".join(lines)[:4000]

    def send(self) -> bool:
        try:
            import requests
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            chat = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
            if not token:
                logger.info(f"[회차요약] 토큰 없음 — 로그만: {self.summary_line()}")
                return False
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": self.text(), "parse_mode": "HTML",
                                    "disable_web_page_preview": True}, timeout=10)
            return r.ok
        except Exception as e:
            logger.warning(f"[회차요약] DM 실패(무시): {e}")
            return False
