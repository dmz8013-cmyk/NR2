import requests
from bs4 import BeautifulSoup

sites = {
    "Ground News": "https://ground.news/",
    "AI Times": "https://www.aitimes.com/",
    "Coinness": "https://coinness.com/news"
}

for name, url in sites.items():
    print(f"\n{'='*60}")
    print(f"📰 {name}: {url}")
    print('='*60)
    
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        
        # 제목 링크 찾기 (일반적인 셀렉터들)
        selectors = [
            "article a",
            "div.news a",
            "div.article a", 
            "h2 a",
            "h3 a",
            "a.title",
            "a.headline"
        ]
        
        found = False
        for selector in selectors:
            articles = soup.select(selector)[:3]
            if articles:
                print(f"\n✅ 셀렉터: {selector}")
                for i, a in enumerate(articles, 1):
                    title = a.get_text(strip=True)
                    link = a.get("href", "")
                    if title and len(title) > 10:
                        print(f"  {i}. {title[:60]}...")
                        print(f"     링크: {link[:80]}...")
                        found = True
                if found:
                    break
        
        if not found:
            print("❌ 기사를 찾을 수 없습니다.")
            
    except Exception as e:
        print(f"❌ 오류: {e}")

print("\n" + "="*60)
