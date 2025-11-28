from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import Brand, Product
from config.database import db

bp = Blueprint('brands', __name__)


@bp.route('/admin/brands')
def list_brands():
    """Hiển thị danh sách brands"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    brands = Brand.query.all()
    return render_template('backend/pages/brands/list.html', brands=brands)


@bp.route('/admin/brands/add', methods=['GET', 'POST'])
def add_brand():
    """Thêm brand mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        
        if not name:
            flash('Tên hãng không được để trống', 'error')
            return render_template('backend/pages/brands/add.html')
        
        # Kiểm tra brand đã tồn tại chưa
        existing_brand = Brand.query.filter_by(Name=name).first()
        if existing_brand:
            flash('Hãng đã tồn tại', 'error')
            return render_template('backend/pages/brands/add.html')
        
        try:
            new_brand = Brand(Name=name)
            db.session.add(new_brand)
            db.session.commit()
            flash('Thêm hãng thành công', 'success')
            return redirect(url_for('brands.list_brands'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm hãng: {str(e)}', 'error')
    
    return render_template('backend/pages/brands/add.html')


@bp.route('/admin/brands/<int:brand_id>')
def detail_brand(brand_id):
    """Chi tiết và chỉnh sửa brand"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    brand = Brand.query.get_or_404(brand_id)
    products = Product.query.filter_by(BrandID=brand_id).all()
    
    return render_template('backend/pages/brands/detail.html', 
                         brand=brand, 
                         products=products)


@bp.route('/admin/brands/<int:brand_id>/edit', methods=['POST'])
def edit_brand(brand_id):
    """Cập nhật brand"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    brand = Brand.query.get_or_404(brand_id)
    
    name = request.form.get('name')
    
    if not name:
        flash('Tên hãng không được để trống', 'error')
        return redirect(url_for('brands.detail_brand', brand_id=brand_id))
    
    # Kiểm tra brand đã tồn tại chưa (trừ brand hiện tại)
    existing_brand = Brand.query.filter(
        Brand.Name == name,
        Brand.BrandID != brand_id
    ).first()
    if existing_brand:
        flash('Hãng đã tồn tại', 'error')
        return redirect(url_for('brands.detail_brand', brand_id=brand_id))
    
    try:
        brand.Name = name
        db.session.commit()
        flash('Cập nhật hãng thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật hãng: {str(e)}', 'error')
    
    return redirect(url_for('brands.detail_brand', brand_id=brand_id))


@bp.route('/admin/brands/<int:brand_id>/delete', methods=['POST'])
def delete_brand(brand_id):
    """Xóa brand"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    brand = Brand.query.get_or_404(brand_id)
    
    # Kiểm tra xem brand có sản phẩm không
    products_count = Product.query.filter_by(BrandID=brand_id).count()
    if products_count > 0:
        flash(f'Không thể xóa hãng vì còn {products_count} sản phẩm', 'error')
        return redirect(url_for('brands.list_brands'))
    
    try:
        db.session.delete(brand)
        db.session.commit()
        flash('Xóa hãng thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa hãng: {str(e)}', 'error')
    
    return redirect(url_for('brands.list_brands'))