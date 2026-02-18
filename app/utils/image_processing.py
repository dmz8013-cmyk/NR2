"""이미지 처리 유틸리티 - Cloudinary 연동"""
import os
import cloudinary
import cloudinary.uploader
from flask import current_app
from werkzeug.utils import secure_filename
from datetime import datetime

def init_cloudinary():
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET')
    )

def save_upload_image(file, upload_folder, prefix='img'):
    try:
        init_cloudinary()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        public_id = f"nr2/{prefix}_{timestamp}"

        result = cloudinary.uploader.upload(
            file,
            public_id=public_id,
            overwrite=True,
            resource_type="image",
            transformation=[
                {'width': 1920, 'crop': 'limit'},
                {'quality': 'auto'},
                {'fetch_format': 'auto'}
            ]
        )
        return result['secure_url']

    except Exception as e:
        current_app.logger.error(f"Cloudinary upload failed: {str(e)}")
        return None

def delete_image(filename, upload_folder):
    try:
        init_cloudinary()
        # Cloudinary URL에서 public_id 추출
        if 'cloudinary.com' in str(filename):
            public_id = filename.split('/upload/')[-1].rsplit('.', 1)[0]
            cloudinary.uploader.destroy(public_id)
        return True
    except Exception as e:
        current_app.logger.error(f"Cloudinary delete failed: {str(e)}")
        return False

def optimize_image(image_path, max_size=1920, max_file_size=1024*1024, quality=85):
    """로컬 파일용 - Cloudinary 사용 시 불필요하지만 호환성 유지"""
    return True
