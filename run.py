import os

# === DB 컬럼/테이블 패치 (create_app 전에 실행) ===
try:
    import psycopg2
    db_url = os.environ.get('DATABASE_URL', '')
    if not db_url:
        db_url = os.environ.get('DATABASE_PRIVATE_URL', '')
    if db_url:
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        cols = {
            'verify_tier': "VARCHAR(20) DEFAULT 'bronze'",
            'verify_category': "VARCHAR(30)",
            'verify_badge': "VARCHAR(50)",
            'verified_at': "TIMESTAMP",
            'bones': "FLOAT DEFAULT 0.0",
            'total_bias_votes': "INTEGER DEFAULT 0",
            'accurate_votes': "INTEGER DEFAULT 0",
        }
        for col, ctype in cols.items():
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
                print(f"[DB PATCH] Added: users.{col}")
            except Exception:
                conn.rollback()
                conn.autocommit = True
        for sql in [
            """CREATE TABLE IF NOT EXISTS news_articles (
                id SERIAL PRIMARY KEY, title VARCHAR(300) NOT NULL,
                url VARCHAR(500) NOT NULL UNIQUE, source VARCHAR(100),
                summary TEXT, image_url VARCHAR(500),
                vote_left INTEGER DEFAULT 0, vote_center INTEGER DEFAULT 0,
                vote_right INTEGER DEFAULT 0, vote_total INTEGER DEFAULT 0,
                confidence FLOAT DEFAULT 0.0, created_at TIMESTAMP DEFAULT NOW(),
                submitted_by INTEGER REFERENCES users(id))""",
            """CREATE TABLE IF NOT EXISTS bias_votes (
                id SERIAL PRIMARY KEY, bias VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                user_id INTEGER REFERENCES users(id),
                article_id INTEGER REFERENCES news_articles(id),
                UNIQUE(user_id, article_id))""",
            """CREATE TABLE IF NOT EXISTS bone_transactions (
                id SERIAL PRIMARY KEY, amount FLOAT NOT NULL,
                reason VARCHAR(100) NOT NULL, created_at TIMESTAMP DEFAULT NOW(),
                user_id INTEGER REFERENCES users(id))""",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                conn.rollback()
                conn.autocommit = True
        cur.close()
        conn.close()
        print("[DB PATCH] Complete!")
except Exception as e:
    print(f"[DB PATCH] Skip: {e}")

# === 앱 시작 ===
from app import create_app, db
from app.models import User, Post, PostImage, Comment, Like, Vote, VoteOption, VoteResponse, Event

app = create_app(os.getenv('FLASK_ENV', 'development'))


@app.shell_context_processor
def make_shell_context():
    return {
        'db': db, 'User': User, 'Post': Post, 'PostImage': PostImage,
        'Comment': Comment, 'Like': Like, 'Vote': Vote,
        'VoteOption': VoteOption, 'VoteResponse': VoteResponse, 'Event': Event,
    }


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
