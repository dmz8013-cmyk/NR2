"""
일회성 스크립트: AESA 게시판의 이준석 관련 자동 게시글 삭제
실행: python run_once.py
"""
import os
import sys

def delete_aesa_lee_posts():
    """AESA 게시판에서 이준석 관련 자동 게시글 삭제"""
    db_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_PRIVATE_URL', '')
    if not db_url:
        print("[ERROR] DATABASE_URL 환경변수가 없습니다.")
        sys.exit(1)

    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # 이준석 관련 AESA 게시글 조회
        cur.execute("""
            SELECT id, title, created_at
            FROM posts
            WHERE board_type = 'aesa'
              AND (title ILIKE '%%이준석%%' OR content ILIKE '%%이준석%%')
        """)
        rows = cur.fetchall()
        print(f"\n[AESA 이준석 관련 게시글] {len(rows)}건 발견:")
        for r in rows:
            print(f"  - ID {r[0]}: {r[1]} ({r[2]})")

        if not rows:
            print("삭제할 게시글이 없습니다.")
            conn.close()
            return

        # 확인 프롬프트
        confirm = input(f"\n위 {len(rows)}건을 삭제하시겠습니까? (yes/no): ")
        if confirm.strip().lower() != 'yes':
            print("취소되었습니다.")
            conn.close()
            return

        ids = [r[0] for r in rows]
        placeholders = ','.join(['%s'] * len(ids))

        # 관련 댓글, 좋아요, 이미지 먼저 삭제
        cur.execute(f"DELETE FROM comments WHERE post_id IN ({placeholders})", ids)
        print(f"  댓글 {cur.rowcount}건 삭제")

        cur.execute(f"DELETE FROM post_votes WHERE post_id IN ({placeholders})", ids)
        print(f"  추천 {cur.rowcount}건 삭제")

        cur.execute(f"DELETE FROM post_images WHERE post_id IN ({placeholders})", ids)
        print(f"  이미지 {cur.rowcount}건 삭제")

        # 게시글 삭제
        cur.execute(f"DELETE FROM posts WHERE id IN ({placeholders})", ids)
        print(f"  게시글 {cur.rowcount}건 삭제")

        conn.commit()
        print("\n[완료] AESA 이준석 관련 게시글 삭제 완료!")
        cur.close()
        conn.close()

    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == '__main__':
    delete_aesa_lee_posts()
