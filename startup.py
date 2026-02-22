import os
import sys

# Railway DB URL 찾기 (여러 환경변수명 시도)
db_url = None
for key in ['DATABASE_URL', 'DATABASE_PRIVATE_URL', 'DATABASE_PUBLIC_URL', 'PGHOST']:
    val = os.environ.get(key)
    if val and 'postgres' in val:
        db_url = val
        print(f"Found DB URL in {key}")
        break

if not db_url:
    # PGHOST가 있으면 직접 조합
    pghost = os.environ.get('PGHOST')
    pguser = os.environ.get('PGUSER', 'postgres')
    pgpass = os.environ.get('PGPASSWORD', '')
    pgdb = os.environ.get('PGDATABASE', 'railway')
    pgport = os.environ.get('PGPORT', '5432')
    if pghost:
        db_url = f"postgresql://{pguser}:{pgpass}@{pghost}:{pgport}/{pgdb}"
        print(f"Built DB URL from PG* vars: {pghost}")

if not db_url:
    print("WARNING: No database URL found! Env vars:")
    for k, v in sorted(os.environ.items()):
        if any(x in k.upper() for x in ['DB', 'PG', 'SQL', 'DATA']):
            print(f"  {k}={v[:20]}...")
    print("Skipping DB setup, starting app anyway...")
    sys.exit(0)

if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

try:
    import psycopg2
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

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
            print(f"Added: users.{col}")
        except Exception as e:
            conn.rollback()
            conn.autocommit = True
            if 'already exists' in str(e) or 'DuplicateColumn' in str(type(e)):
                pass
            else:
                print(f"Column {col} skip: {e}")

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
    print("news_articles ready")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bias_votes (
        id SERIAL PRIMARY KEY,
        bias VARCHAR(10) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        user_id INTEGER REFERENCES users(id),
        article_id INTEGER REFERENCES news_articles(id),
        UNIQUE(user_id, article_id)
    )""")
    print("bias_votes ready")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bone_transactions (
        id SERIAL PRIMARY KEY,
        amount FLOAT NOT NULL,
        reason VARCHAR(100) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        user_id INTEGER REFERENCES users(id)
    )""")
    print("bone_transactions ready")

    cur.close()
    conn.close()
    print("=== DB SETUP COMPLETE ===")
except Exception as e:
    print(f"DB setup error: {e}")
    print("Starting app anyway...")
    sys.exit(0)
