#!/usr/bin/env python3
"""회원가입 테스트"""
import requests

BASE_URL = "http://localhost:5001"

print("=" * 50)
print("회원가입 테스트 시작")
print("=" * 50)

# 1. 회원가입 시도
print("\n1. 회원가입 시도 (newuser@test.com)...")
session = requests.Session()
response = session.post(
    f"{BASE_URL}/auth/register",
    data={
        'email': 'newuser@test.com',
        'nickname': '신규유저',
        'password': 'test1234',
        'password_confirm': 'test1234'
    },
    allow_redirects=False
)

print(f"   상태 코드: {response.status_code}")
if response.status_code == 302:
    print(f"   ✓ 리다이렉트: {response.headers.get('Location')}")
    print("   ✓ 회원가입 성공!")
else:
    print("   ✗ 회원가입 실패")
    # 에러 메시지 확인
    if '이미 사용 중' in response.text:
        print("   (이미 가입된 이메일/닉네임)")

# 2. 중복 이메일 테스트
print("\n2. 중복 이메일 테스트...")
response = session.post(
    f"{BASE_URL}/auth/register",
    data={
        'email': 'admin@nr2.com',  # 이미 존재하는 이메일
        'nickname': '다른닉네임',
        'password': 'test1234',
        'password_confirm': 'test1234'
    },
    allow_redirects=False
)

if response.status_code == 200 and '이미 사용 중인 이메일' in response.text:
    print("   ✓ 중복 이메일 검증 작동")
else:
    print("   상태 코드:", response.status_code)

# 3. 비밀번호 불일치 테스트
print("\n3. 비밀번호 불일치 테스트...")
response = session.post(
    f"{BASE_URL}/auth/register",
    data={
        'email': 'test@test.com',
        'nickname': '테스트',
        'password': 'test1234',
        'password_confirm': 'different'
    },
    allow_redirects=False
)

if response.status_code == 200 and '일치하지 않습니다' in response.text:
    print("   ✓ 비밀번호 불일치 검증 작동")
else:
    print("   상태 코드:", response.status_code)

# 4. 가입 후 로그인 테스트
print("\n4. 신규 계정 로그인 테스트...")
session2 = requests.Session()
response = session2.post(
    f"{BASE_URL}/auth/login",
    data={
        'email': 'newuser@test.com',
        'password': 'test1234'
    },
    allow_redirects=False
)

if response.status_code == 302:
    print("   ✓ 신규 계정 로그인 성공")
else:
    print("   ✗ 로그인 실패")

print("\n" + "=" * 50)
print("✅ 회원가입 테스트 완료!")
print("=" * 50)
