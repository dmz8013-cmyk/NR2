"""이미지 처리 유틸리티"""
import os
from PIL import Image
from flask import current_app
from werkzeug.utils import secure_filename
from datetime import datetime


def optimize_image(image_path, max_size=1920, max_file_size=1024*1024, quality=85):
    """
    이미지 최적화 및 리사이징

    Args:
        image_path: 이미지 파일 경로
        max_size: 최대 가로/세로 크기 (픽셀)
        max_file_size: 최대 파일 크기 (바이트)
        quality: JPEG 품질 (1-100)

    Returns:
        bool: 성공 여부
    """
    try:
        with Image.open(image_path) as img:
            # EXIF 방향 정보 처리
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # 리사이징
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # RGB로 변환 (RGBA나 다른 모드인 경우)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 파일 크기 최적화
            temp_path = image_path + '.tmp'
            current_quality = quality

            while current_quality >= 30:
                img.save(temp_path, 'JPEG', quality=current_quality, optimize=True)

                # 파일 크기 확인
                file_size = os.path.getsize(temp_path)

                if file_size <= max_file_size or current_quality <= 30:
                    break

                current_quality -= 5

            # 원본 파일 교체
            os.replace(temp_path, image_path)

            return True

    except Exception as e:
        current_app.logger.error(f"Image optimization failed: {str(e)}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def save_upload_image(file, upload_folder, prefix='img'):
    """
    업로드된 이미지 저장 및 최적화

    Args:
        file: 업로드된 파일 객체
        upload_folder: 저장 폴더
        prefix: 파일명 접두사

    Returns:
        str: 저장된 파일명 (None if failed)
    """
    try:
        # 안전한 파일명 생성
        original_filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        name, ext = os.path.splitext(original_filename)
        filename = f"{prefix}_{timestamp}{ext}"

        # 파일 저장
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        # 이미지 최적화
        max_size = current_app.config.get('MAX_IMAGE_SIZE', 1920)
        max_file_size = current_app.config.get('MAX_IMAGE_FILE_SIZE', 1024*1024)

        if not optimize_image(filepath, max_size, max_file_size):
            current_app.logger.warning(f"Image optimization failed for {filename}")

        return filename

    except Exception as e:
        current_app.logger.error(f"Image save failed: {str(e)}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None


def delete_image(filename, upload_folder):
    """
    이미지 파일 삭제

    Args:
        filename: 파일명
        upload_folder: 저장 폴더

    Returns:
        bool: 성공 여부
    """
    try:
        filepath = os.path.join(upload_folder, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False
    except Exception as e:
        current_app.logger.error(f"Image delete failed: {str(e)}")
        return False
