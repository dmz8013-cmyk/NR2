import requests
from bs4 import BeautifulSoup

# 네이버 뉴스 정치 섹션
r = requests.get("https://news.naver.com/section/100", 
                headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
soup = BeautifulSoup(r.text, "html.parser")

print("=== 네이버 뉴스 구조 분석 ===\n")

# 기사 요소 찾기
articles = soup.select("div.sa_text")[:3]

for i, article in enumerate(articles, 1):
    print(f"📰 기사 {i}:")
    print(f"전체 HTML: {article}")
    print("\n" + "="*50 + "\n")
    
    # 제목
    title_elem = article.select_one("a.sa_text_title")
    if title_elem:
        print(f"제목: {title_elem.get_text(strip=True)}")
    
    # 시간 요소들 모두 찾기
    print(f"\n시간 관련 요소들:")
    time_candidates = [
        article.select_one("div.sa_text_time"),
        article.select_one("span.sa_text_time"),
        article.select_one("div.sa_text_datetime"),
        article.select_one("span.sa_text_datetime"),
        article.select_one("div.sa_text_info_left"),
        article.select_one("div.sa_text_info"),
    ]
    
    for elem in time_candidates:
        if elem:
            print(f"  - {elem.name}.{elem.get('class')}: {elem.get_text(strip=True)}")
    
    print("\n" + "="*50 + "\n")
