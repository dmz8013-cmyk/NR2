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
        # source_bias 컬럼 패치
        for col in ['source_political', 'source_geopolitical', 'source_economic']:
            try:
                cur.execute(f"ALTER TABLE news_articles ADD COLUMN {col} FLOAT")
                print(f"[DB PATCH] Added: news_articles.{col}")
            except Exception:
                conn.rollback()
                conn.autocommit = True
        for sql in [
            """CREATE TABLE IF NOT EXISTS news_articles (
                id SERIAL PRIMARY KEY, title VARCHAR(300) NOT NULL,
                url VARCHAR(500) NOT NULL UNIQUE, source VARCHAR(100),
                summary TEXT, image_url VARCHAR(500),
                source_political FLOAT, source_geopolitical FLOAT, source_economic FLOAT,
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
            """CREATE TABLE IF NOT EXISTS briefings (
                id SERIAL PRIMARY KEY,
                briefing_type VARCHAR(20) NOT NULL,
                title VARCHAR(200),
                content TEXT NOT NULL,
                article_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW())""",
        ]:
            try:
                cur.execute(sql)
            except Exception:
                conn.rollback()
                conn.autocommit = True
        # 방법론 공지 INSERT (중복 방지)
        try:
            cur.execute("""
                INSERT INTO breaking_news (title, content, source, priority, is_active, user_id, created_at, updated_at)
                SELECT %s, %s, %s, %s, TRUE, 1, NOW(), NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM breaking_news WHERE title = %s
                )
            """, (
                '📊 NR2 언론사 편향 분류 방법론 공개',
                '''NR2 YouCheck(뉴스 편향 분석) 기능이 출시되었습니다.

YouCheck은 한국 주요 언론사 50개의 보도 성향을 3개 축(정치, 지정학, 경제)으로 분류하여 시각화합니다.

기존의 단순한 '진보 vs 보수' 이분법을 넘어, 지정학적 입장(친중↔친미)과 경제적 성향(노동친화↔대기업친화)까지 포함한 다면적 분석을 제공합니다.

📌 주요 기능:
• 기사별 시민 편향 투표 (좌/중/우)
• 언론사 3축 성향 바 자동 표시
• 전문가/일반 시민 가중치 차등 반영

📄 분류 방법론 전문 보기:
https://nr2.kr/methodology

여러분의 적극적인 참여를 부탁드립니다.
YouCheck 바로가기: https://nr2.kr/bias''',
                'NR2 운영팀',
                5,
                '📊 NR2 언론사 편향 분류 방법론 공개',
            ))
            if cur.rowcount > 0:
                print("[DB PATCH] 방법론 공지 등록 완료")
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
