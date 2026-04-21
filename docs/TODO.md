# 중기 기술 백로그

## Alembic 마이그레이션 정상화 — 6월 중순(선거 종료) 이후

**현 상태 (2026-04-21):**
- `app/__init__.py:168`에 `db.create_all()`이 남아 있어 모든 Flask 부팅 시 모델 기반으로 테이블을 자동 생성한다.
- Alembic migration(`flask db upgrade`)은 Procfile `release:` 단계에서 실행되어야 하지만, `create_all`이 먼저 테이블을 만들어버려 Alembic의 `CREATE TABLE`이 충돌(`relation already exists`)로 실패한다.
- 결과: Alembic + create_all 혼용. `alembic_version` 기록이 실제 스키마와 어긋나며 실질 관리되지 않는다.
- 신규 스키마 변경 시마다 이번(2026-04-21 URL shortener)처럼 수동 `CREATE INDEX IF NOT EXISTS` + `UPDATE alembic_version`으로 봉합해야 함.

**해결 과제:**
- [ ] `app/__init__.py:168`의 `db.create_all()` 제거
- [ ] `app/__init__.py:204, :521`의 수동 ALTER TABLE 블록을 정상 migration으로 이관
- [ ] 누락된 migration 체인 검증: 현재 DB에 적용된 리비전(`f7a8b9c0d1e2` 수동 stamp)과 파일 시스템상 리비전(`fc11034da528 → c863f861fcbb → cc831318bbbf → d4e5f6a7b8c9 → e1a2b3c4d5e6 → f7a8b9c0d1e2`)의 정합성 확인
- [ ] `d4e5f6a7b8c9`, `e1a2b3c4d5e6`이 실제 DB에 반영됐는지 컬럼 레벨에서 점검 (필요 시 stamp 또는 실제 반영)
- [ ] Railway의 Procfile `release:` 실행 메커니즘 확인 (Nixpacks/Railpack 빌더별 동작 차이)

**일정 제약:**
선거 기간 중(~2026-06-15) 스키마 리팩터는 운영 리스크. 종료 후 별도 세션에서 점검.
