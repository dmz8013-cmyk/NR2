"""Railway 시작 스크립트 - 직접 SQL로 DB 업데이트 후 서버 실행"""
import os
import psycopg2

db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

if db_url:
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        # 1. users 테이블에 누락 컬럼 추가
        columns = {
            'verify_tier': "VARCHAR(20) DEFAULT 'bronze'",
            'verify_category': "VARCHAR(30)",
            'verify_badge': "VARCHAR(50)",
            'verified_at': "TIMESTAMP",
            'bones': "FLOAT DEFAULT 0.0",
            'total_bias_votes': "INTEGER DEFAULT 0",
            'accurate_votes': "INTEGER DEFAULT 0",
        }
        for col, col_type in columns.items():
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                print(f"Added column: users.{col}")
            except psycopg2.errors.DuplicateColumn:
                conn.rollback()
                conn.autocommit = True

        # 2. 새 테이블 생성
        cur.execute("""
        CREATE TABLE IF NOT EXISTS news_articles (
            id SERIAL PRIMARY KEY,
            title VARCHAR(300) NOT NULL,
            url VARCHAR(500) NOT NULL UNIQUE,
            source VARCHAR(100),
            summary TEXT,
            image_url VARCHAR(500),
            vote_left INTEGER DEFAULT 0,
            vote_center INTEGER DEFAULT 0,
            vote_right INTEGER DEFAULT 0,
            vote_total INTEGER DEFAULT 0,
            confidence FLOAT DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT NOW(),
            submitted_by INTEGER REFERENCES users(id)
        )""")
        print("news_articles table ready")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS bias_votes (
            id SERIAL PRIMARY KEY,
            bias VARCHAR(10) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            user_id INTEGER REFERENCES users(id),
            article_id INTEGER REFERENCES news_articles(id),
            UNIQUE(user_id, article_id)
        )""")
        print("bias_votes table ready")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS bone_transactions (
            id SERIAL PRIMARY KEY,
            amount FLOAT NOT NULL,
            reason VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            user_id INTEGER REFERENCES users(id)
        )""")
        print("bone_transactions table ready")

        cur.close()
        conn.close()
        print("=== DB SETUP COMPLETE ===")
    except Exception as e:
        print(f"DB setup error: {e}")
else:
    print("No DATABASE_URL found, skipping DB setup")
