"""
NR2 PWA 아이콘 생성 스크립트
실행: pip install Pillow cairosvg && python generate_icons.py
아이콘을 app/static/icons/ 에 생성합니다.
"""
import os

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("pip install Pillow 실행 후 다시 시도하세요")
    exit(1)

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "app", "static", "icons")

def generate_icon(size):
    """NR2 브랜드 아이콘 생성 (🌐 + 골드 테마)"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 배경: 라운드 사각형 (다크네이비)
    padding = int(size * 0.05)
    radius = int(size * 0.18)
    draw.rounded_rectangle(
        [padding, padding, size - padding, size - padding],
        radius=radius,
        fill=(26, 26, 46, 255)  # #1a1a2e
    )

    # 텍스트: NR2
    font_size = int(size * 0.32)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    text = "NR2"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2 - int(size * 0.05)
    draw.text((x, y), text, fill=(245, 166, 35, 255), font=font)  # #f5a623

    # 서브텍스트
    sub_size = int(size * 0.11)
    try:
        sub_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sub_size)
    except (OSError, IOError):
        try:
            sub_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", sub_size)
        except (OSError, IOError):
            sub_font = ImageFont.load_default()

    sub_text = "NETWORK"
    sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_x = (size - sub_w) // 2
    sub_y = y + text_h + int(size * 0.04)
    draw.text((sub_x, sub_y), sub_text, fill=(200, 200, 200, 255), font=sub_font)

    return img

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for size in SIZES:
        img = generate_icon(size)
        filepath = os.path.join(OUTPUT_DIR, f"icon-{size}x{size}.png")
        img.save(filepath, "PNG")
        print(f"✅ {filepath} ({size}x{size})")

    # favicon.ico (32x32 + 16x16)
    img_32 = generate_icon(32)
    img_16 = generate_icon(16)
    favicon_path = os.path.join(OUTPUT_DIR, "..", "favicon.ico")
    img_32.save(favicon_path, format="ICO", sizes=[(16, 16), (32, 32)])
    print(f"✅ {favicon_path} (favicon)")

    print(f"\n🎉 총 {len(SIZES)}개 아이콘 + favicon 생성 완료!")
    print(f"📁 경로: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
