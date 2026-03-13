"""
이중 이스케이프된 게시글 HTML 복구 스크립트
&lt;p&gt; → <p>, &lt;/p&gt; → </p> 등으로 치환

사용법:
  python fix_double_escape.py          # 미리보기 (dry-run)
  python fix_double_escape.py --apply  # 실제 적용
"""
import sys
from app import create_app
from app import db
from app.models import Post

def fix_double_escape(apply=False):
    app = create_app()
    with app.app_context():
        # 이중 이스케이프된 게시글 조회
        affected = Post.query.filter(Post.content.like('%&lt;%')).all()
        print(f"이중 이스케이프된 게시글: {len(affected)}건")

        if not affected:
            print("복구할 게시글이 없습니다.")
            return

        for post in affected:
            original = post.content
            fixed = (original
                     .replace('&lt;', '<')
                     .replace('&gt;', '>')
                     .replace('&amp;', '&')
                     .replace('&quot;', '"')
                     .replace('&#x27;', "'")
                     .replace('&#39;', "'"))

            print(f"\n[ID {post.id}] {post.title}")
            print(f"  Before: {original[:120]}...")
            print(f"  After:  {fixed[:120]}...")

            if apply:
                post.content = fixed

        if apply:
            db.session.commit()
            print(f"\n{len(affected)}건 복구 완료!")
        else:
            print(f"\n--apply 옵션으로 실행하면 {len(affected)}건이 복구됩니다.")

if __name__ == '__main__':
    apply = '--apply' in sys.argv
    fix_double_escape(apply=apply)
