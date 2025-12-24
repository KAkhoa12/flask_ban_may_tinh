"""
Script để sửa đường dẫn ảnh bị lỗi trong database
Chạy script này để sửa các đường dẫn có /static//static/ thành đường dẫn đúng
"""
import sys
import os

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from config.database import db
from models.tables import Product

def fix_image_paths():
    """Sửa đường dẫn ảnh bị lỗi"""
    with app.app_context():
        # Tìm tất cả sản phẩm có đường dẫn ảnh
        products = Product.query.filter(Product.ImageURL.isnot(None)).all()
        
        fixed_count = 0
        for product in products:
            original_url = product.ImageURL
            
            # Kiểm tra nếu có /static//static/ hoặc /static/static/
            if '/static//static/' in original_url or '/static/static/' in original_url:
                # Sửa đường dẫn
                fixed_url = original_url.replace('/static//static/', '')
                fixed_url = fixed_url.replace('/static/static/', '')
                fixed_url = fixed_url.replace('/static/', '')
                
                product.ImageURL = fixed_url
                fixed_count += 1
                
                print(f"✅ Sửa sản phẩm ID {product.ProductID}: {product.Name}")
                print(f"   Trước: {original_url}")
                print(f"   Sau:  {fixed_url}")
                print()
            
            # Kiểm tra nếu có /static/ ở đầu (cũng cần sửa)
            elif original_url.startswith('/static/'):
                fixed_url = original_url.replace('/static/', '')
                product.ImageURL = fixed_url
                fixed_count += 1
                
                print(f"✅ Sửa sản phẩm ID {product.ProductID}: {product.Name}")
                print(f"   Trước: {original_url}")
                print(f"   Sau:  {fixed_url}")
                print()
        
        if fixed_count > 0:
            db.session.commit()
            print(f"\n🎉 Đã sửa {fixed_count} sản phẩm!")
        else:
            print("\n✨ Không có sản phẩm nào cần sửa!")

if __name__ == "__main__":
    print("=" * 60)
    print("  SCRIPT SỬA ĐƯỜNG DẪN ẢNH")
    print("=" * 60)
    print()
    
    fix_image_paths()
