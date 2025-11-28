from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import Category, Product
from config.database import db

bp = Blueprint('categories', __name__)


@bp.route('/admin/categories')
def list_categories():
    """Hiển thị danh sách categories"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    categories = Category.query.all()
    return render_template('backend/pages/categories/list.html', categories=categories)


@bp.route('/admin/categories/add', methods=['GET', 'POST'])
def add_category():
    """Thêm category mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        parent_id = request.form.get('parent_id')
        
        if not name:
            flash('Tên danh mục không được để trống', 'error')
            return render_template('backend/pages/categories/add.html')
        
        # Kiểm tra category đã tồn tại chưa
        existing_category = Category.query.filter_by(Name=name).first()
        if existing_category:
            flash('Danh mục đã tồn tại', 'error')
            return render_template('backend/pages/categories/add.html')
        
        try:
            new_category = Category(
                Name=name,
                ParentID=int(parent_id) if parent_id else None
            )
            db.session.add(new_category)
            db.session.commit()
            flash('Thêm danh mục thành công', 'success')
            return redirect(url_for('categories.list_categories'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi thêm danh mục: {str(e)}', 'error')
    
    # Lấy danh sách categories để làm parent
    parent_categories = Category.query.filter_by(ParentID=None).all()
    return render_template('backend/pages/categories/add.html', parent_categories=parent_categories)


@bp.route('/admin/categories/<int:category_id>')
def detail_category(category_id):
    """Chi tiết và chỉnh sửa category"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    category = Category.query.get_or_404(category_id)
    products = Product.query.filter_by(CategoryID=category_id).all()
    parent_categories = Category.query.filter_by(ParentID=None).all()
    
    return render_template('backend/pages/categories/detail.html', 
                         category=category, 
                         products=products,
                         parent_categories=parent_categories)


@bp.route('/admin/categories/<int:category_id>/edit', methods=['POST'])
def edit_category(category_id):
    """Cập nhật category"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    category = Category.query.get_or_404(category_id)
    
    name = request.form.get('name')
    parent_id = request.form.get('parent_id')
    
    if not name:
        flash('Tên danh mục không được để trống', 'error')
        return redirect(url_for('categories.detail_category', category_id=category_id))
    
    # Kiểm tra category đã tồn tại chưa (trừ category hiện tại)
    existing_category = Category.query.filter(
        Category.Name == name,
        Category.CategoryID != category_id
    ).first()
    if existing_category:
        flash('Danh mục đã tồn tại', 'error')
        return redirect(url_for('categories.detail_category', category_id=category_id))
    
    try:
        category.Name = name
        category.ParentID = int(parent_id) if parent_id else None
        db.session.commit()
        flash('Cập nhật danh mục thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật danh mục: {str(e)}', 'error')
    
    return redirect(url_for('categories.detail_category', category_id=category_id))


@bp.route('/admin/categories/<int:category_id>/delete', methods=['POST'])
def delete_category(category_id):
    """Xóa category"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    category = Category.query.get_or_404(category_id)
    
    # Kiểm tra xem category có sản phẩm không
    products_count = Product.query.filter_by(CategoryID=category_id).count()
    if products_count > 0:
        flash(f'Không thể xóa danh mục vì còn {products_count} sản phẩm', 'error')
        return redirect(url_for('categories.list_categories'))
    
    # Kiểm tra xem category có category con không
    children_count = Category.query.filter_by(ParentID=category_id).count()
    if children_count > 0:
        flash(f'Không thể xóa danh mục vì còn {children_count} danh mục con', 'error')
        return redirect(url_for('categories.list_categories'))
    
    try:
        db.session.delete(category)
        db.session.commit()
        flash('Xóa danh mục thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa danh mục: {str(e)}', 'error')
    
    return redirect(url_for('categories.list_categories'))