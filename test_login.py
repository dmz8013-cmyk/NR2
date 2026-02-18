#!/usr/bin/env python3
"""로그인 테스트"""
import requests

BASE_URL = "http://localhost:5001"

# 세션 생성
session = requests.Session()

print("=" * 50)
print("로그인 테스트 시작")
print("=" * 50)

# 1. 로그인 시도
print("\n1. 로그인 시도 (admin@nr2.com / admin1234)...")
response = session.post(
    f"{BASE_URL}/auth/login",
    data={
        'email': 'admin@nr2.com',
        'password': 'admin1234',
        'remember': 'on'
    },
    allow_redirects=False
)

print(f"   상태 코드: {response.status_code}")
if response.status_code == 302:
    print(f"   ✓ 리다이렉트: {response.headers.get('Location')}")
    print("   ✓ 로그인 성공!")
else:
    print("   ✗ 로그인 실패")

# 2. 메인 페이지 접속 (로그인 상태 확인)
print("\n2. 메인 페이지 접속 (로그인 상태 확인)...")
response = session.get(f"{BASE_URL}/")
if '관리자님' in response.text:
    print("   ✓ 로그인 상태 유지됨")
    print("   ✓ 네비게이션에 '관리자님' 표시")
elif '로그아웃' in response.text:
    print("   ✓ 로그인 상태 유지됨")
    print("   ✓ 로그아웃 버튼 표시")
else:
    print("   ✗ 로그인 상태가 유지되지 않음")

# 3. 관리자 페이지 접속 시도
print("\n3. 관리자 대시보드 접속 시도...")
response = session.get(f"{BASE_URL}/admin/", allow_redirects=False)
print(f"   상태 코드: {response.status_code}")
if response.status_code == 200:
    print("   ✓ 관리자 페이지 접근 성공")
else:
    print(f"   접근 불가 (관리자 페이지 미구현)")

# 4. 로그아웃
print("\n4. 로그아웃 테스트...")
response = session.get(f"{BASE_URL}/auth/logout", allow_redirects=False)
print(f"   상태 코드: {response.status_code}")
if response.status_code == 302:
    print("   ✓ 로그아웃 성공")

# 5. 로그아웃 후 메인 페이지
print("\n5. 로그아웃 후 메인 페이지 확인...")
response = session.get(f"{BASE_URL}/")
if '로그인' in response.text and '회원가입' in response.text:
    print("   ✓ 로그인/회원가입 버튼 표시")
    print("   ✓ 로그아웃 상태 확인")
else:
    print("   ✗ 로그아웃 상태가 올바르지 않음")

print("\n" + "=" * 50)
print("✅ 로그인 테스트 완료!")
print("=" * 50)
