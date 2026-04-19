import asyncio
from playwright.async_api import async_playwright
import datetime

async def get_html():
    today = datetime.datetime.now().strftime("%Y%m%d")
    url = f"https://news.naver.com/opinion/editorial?date={today}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        with open("/Users/parkjongwon/NR2/scratch_naver.html", "w") as f:
            f.write(html)
        await browser.close()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(get_html())
