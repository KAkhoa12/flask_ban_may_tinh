from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from models.tables import Product, Category, Brand
from config.database import db
import os
import uuid
from werkzeug.utils import secure_filename

bp = Blueprint('products', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file):
    """Lưu file upload và trả về đường dẫn"""
    if file and allowed_file(file.filename):
        # Tạo tên file unique
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        
        # Tạo thư mục upload nếu chưa có
        upload_folder = os.path.join(current_app.static_folder, 'images', 'products')
        os.makedirs(upload_folder, exist_ok=True)
        
        # Lưu file
        file_path = os.path.join(upload_folder, unique_filename)
        file.save(file_path)
        
        # Trả về đường dẫn relative
        return f"images/products/{unique_filename}"
    return None


@bp.route('/admin/products')
def list_products():
    """Hiển thị danh sách products"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy tham số filter từ request
    category_filter = request.args.get('category_filter')
    brand_filter = request.args.get('brand_filter')
    search = request.args.get('search')
    
    # Bắt đầu với query cơ bản
    query = Product.query
    
    # Áp dụng filter theo category
    if category_filter:
        query = query.filter(Product.CategoryID == category_filter)
    
    # Áp dụng filter theo brand
    if brand_filter:
        query = query.filter(Product.BrandID == brand_filter)
    
    # Áp dụng tìm kiếm theo tên
    if search:
        query = query.filter(Product.Name.contains(search))
    
    # Lấy kết quả
    products = query.all()
    
    # Lấy danh sách categories và brands cho filter dropdown
    categories = Category.query.all()
    brands = Brand.query.all()
    
    return render_template('backend/pages/products/list.html', 
                         products=products, 
                         categories=categories, 
                         brands=brands)


@bp.route('/admin/products/add', methods=['GET', 'POST'])
def add_product():
    """Thêm product mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        price = request.form.get('price')
        stock = request.form.get('stock')
        category_id = request.form.get('category')
        brand_id = request.form.get('brand')
        specs = request.form.get('specs')
        is_pc = request.form.get('is_pc', 0)  # Mặc định là 0 (false) cho sản phẩm linh kiện
        image_file = request.files.get('image')
        
        # Validation
        if not all([name, price, stock, category_id]):
            flash('Vui lòng điền đầy đủ thông tin bắt buộc', 'error')
            return render_template('backend/pages/products/add.html', 
                                 categories=Category.query.all(), 
                                 brands=Brand.query.all())
        
        try:
            # Xử lý upload ảnh
            image_url = None
            if image_file:
                image_url = save_uploaded_file(image_file)
            
            # Tạo product mới
            new_product = Product(
                Name=name,
                Price=float(price),
                Stock=int(stock),
                CategoryID=int(category_id),
                BrandID=int(brand_id) if brand_id else None,
                Specs=specs,
                IsPC=int(is_pc),
                ImageURL=image_url
            )
            
            db.session.add(new_product)
            db.session.commit()
            flash('Thêm sản phẩm thành công', 'success')
            return redirect(url_for('products.list_products'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm sản phẩm: {str(e)}', 'error')
    
    categories = Category.query.all()
    brands = Brand.query.all()
    return render_template('backend/pages/products/add.html', 
                         categories=categories, 
                         brands=brands)


@bp.route('/admin/products/<int:product_id>')
def detail_product(product_id):
    """Chi tiết và chỉnh sửa product"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    product = Product.query.get_or_404(product_id)
    categories = Category.query.all()
    brands = Brand.query.all()
    
    return render_template('backend/pages/products/detail.html', 
                         product=product,
                         categories=categories, 
                         brands=brands)


@bp.route('/admin/products/<int:product_id>/edit', methods=['POST'])
def edit_product(product_id):
    """Cập nhật product"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    product = Product.query.get_or_404(product_id)
    
    name = request.form.get('name')
    price = request.form.get('price')
    stock = request.form.get('stock')
    category_id = request.form.get('category')
    brand_id = request.form.get('brand')
    specs = request.form.get('specs')
    is_pc = request.form.get('is_pc', 0)
    image_file = request.files.get('image')
    
    # Validation
    if not all([name, price, stock, category_id]):
        flash('Vui lòng điền đầy đủ thông tin bắt buộc', 'error')
        return redirect(url_for('products.detail_product', product_id=product_id))
    
    try:
        # Cập nhật thông tin cơ bản
        product.Name = name
        product.Price = float(price)
        product.Stock = int(stock)
        product.CategoryID = int(category_id)
        product.BrandID = int(brand_id) if brand_id else None
        product.Specs = specs
        product.IsPC = int(is_pc)
        
        # Xử lý upload ảnh mới (nếu có)
        if image_file:
            new_image_url = save_uploaded_file(image_file)
            if new_image_url:
                product.ImageURL = new_image_url
        
        db.session.commit()
        flash('Cập nhật sản phẩm thành công', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật sản phẩm: {str(e)}', 'error')
    
    return redirect(url_for('products.detail_product', product_id=product_id))


@bp.route('/admin/products/<int:product_id>/delete', methods=['POST'])
def delete_product(product_id):
    """Xóa product"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    product = Product.query.get_or_404(product_id)
    
    try:
        # Xóa ảnh nếu có
        if product.ImageURL:
            image_path = os.path.join(current_app.static_folder, product.ImageURL)
            if os.path.exists(image_path):
                os.remove(image_path)
        
        db.session.delete(product)
        db.session.commit()
        flash('Xóa sản phẩm thành công', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa sản phẩm: {str(e)}', 'error')
    
    return redirect(url_for('products.list_products'))