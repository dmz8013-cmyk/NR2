"""Railway 시작 스크립트 - DB 마이그레이션 + 서버 실행"""
import subprocess
import sys

# 1. 마이그레이션 시도
try:
    result = subprocess.run(
        ['flask', 'db', 'upgrade'],
        capture_output=True, text=True, timeout=30
    )
    print("=== DB UPGRADE OUTPUT ===")
    print(result.stdout)
    if result.stderr:
        print("=== DB UPGRADE ERRORS ===")
        print(result.stderr)
except Exception as e:
    print(f"Migration failed: {e}")
    # 실패해도 서버는 시작

# 2. 누락된 컬럼 직접 추가 (안전망)
try:
    from app import create_app, db
    app = create_app()
    with app.app_context():
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        
        # users 테이블 컬럼 확인 + 추가
        existing = [c['name'] for c in inspector.get_columns('users')]
        new_cols = {
            'verify_tier': "VARCHAR(20) DEFAULT 'bronze'",
            'verify_category': "VARCHAR(30)",
            'verify_badge': "VARCHAR(50)",
            'verified_at': "TIMESTAMP",
            'bones': "FLOAT DEFAULT 0.0",
            'total_bias_votes': "INTEGER DEFAULT 0",
            'accurate_votes': "INTEGER DEFAULT 0",
        }
        for col, col_type in new_cols.items():
            if col not in existing:
                db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {col_type}'))
                print(f"Added column: users.{col}")
        
        # 새 테이블 생성 (없으면)
        tables = inspector.get_table_names()
        if 'news_articles' not in tables or 'bias_votes' not in tables or 'bone_transactions' not in tables:
            db.create_all()
            print("Created missing tables")
        
        db.session.commit()
        print("=== DB SETUP COMPLETE ===")
except Exception as e:
    print(f"DB setup error: {e}")
