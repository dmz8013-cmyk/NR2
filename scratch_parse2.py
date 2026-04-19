from bs4 import BeautifulSoup
import json

with open("/Users/parkjongwon/NR2/scratch_naver.html", "r") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

item = soup.find(class_='opinion_editorial_item')
if item:
    print(item.prettify())
