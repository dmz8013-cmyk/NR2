from bs4 import BeautifulSoup

with open("/Users/parkjongwon/NR2/scratch_naver.html", "r") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Find the blocks containing the editorial. Typically li or div representing media blocks
# Let's inspect class names that might contain 'editorial' or 'opinion' or 'press'
for element in soup.find_all(class_=lambda x: x and isinstance(x, str) and ('press' in x or 'media' in x or 'editorial' in x or 'news' in x)):
    print(f"Class: {element.get('class')}")

# Try to find '중앙일보'
print("Looking for 중앙일보...")
for element in soup.find_all(string=lambda text: '중앙일보' in text if text else False):
    parent = element.parent
    print(f"Text parent class: {parent.get('class')}")
    # Show ancestors to figure out block container
    p = parent
    for i in range(3):
        if p and p.parent:
            p = p.parent
            print(f"Ancestor {i+1} class: {p.get('class')}")
