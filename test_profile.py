#!/usr/bin/env python3
"""프로필 이미지 기능 테스트"""
import sys
sys.path.insert(0, '/Users/smpark/Desktop/NR2')

from app import create_app, db
from app.models import User
import os

app = create_app('development')

with app.app_context():
    print("=" * 50)
    print("프로필 이미지 기능 테스트")
    print("=" * 50)

    # 사용자 조회
    users = User.query.all()

    print(f"\n총 사용자 수: {len(users)}명")
    print("\n사용자 프로필 이미지 현황:")

    for user in users:
        profile_path = f"app/static/uploads/profiles/{user.profile_image}"
        exists = "✓" if os.path.exists(profile_path) else "✗"
        print(f"\n  [{exists}] {user.nickname}")
        print(f"      이메일: {user.email}")
        print(f"      프로필 이미지: {user.profile_image}")
        print(f"      파일 존재: {os.path.exists(profile_path)}")
        if user.is_admin:
            print(f"      권한: 관리자")

    # 기본 프로필 이미지 확인
    default_path = "app/static/uploads/profiles/default_profile.jpeg"
    print(f"\n기본 프로필 이미지:")
    print(f"  경로: {default_path}")
    print(f"  존재: {os.path.exists(default_path)}")
    if os.path.exists(default_path):
        size = os.path.getsize(default_path)
        print(f"  크기: {size:,} bytes")

    print("\n" + "=" * 50)
    print("✅ 프로필 기능 테스트 완료!")
    print("\n사용 방법:")
    print("  1. 로그인 후 우측 상단 프로필 이미지 클릭")
    print("  2. '프로필' 메뉴 선택")
    print("  3. http://localhost:5001/auth/profile 접속")
    print("  4. 새 이미지 선택 후 업로드")
    print("\n지원 형식: PNG, JPG, JPEG, GIF (최대 16MB)")
