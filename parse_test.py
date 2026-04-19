from bs4 import BeautifulSoup
import re

with open('schedule_test.html', 'r', encoding='utf-8') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')
div = soup.find('div', id='nowNa-text')
text = div.get_text('\n', strip=True) if div else ''

print(text[:500])
