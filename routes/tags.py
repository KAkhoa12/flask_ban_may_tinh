from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import Tag, ProductTag, Product
from config.database import db

bp = Blueprint('tags', __name__)


@bp.route('/admin/tags')
def list_tags():
    """Danh sách nhãn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    tags = Tag.query.all()
    return render_template('backend/pages/tags/list.html', tags=tags)


@bp.route('/admin/tags/add')
def add_tag():
    """Trang thêm nhãn mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    return render_template('backend/pages/tags/add.html')


@bp.route('/admin/tags/add', methods=['POST'])
def save_tag():
    """Lưu nhãn mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        name = request.form.get('name')
        
        if not name:
            flash('Vui lòng nhập tên nhãn!', 'error')
            return redirect(url_for('tags.add_tag'))
        
        # Kiểm tra nhãn đã tồn tại chưa
        existing_tag = Tag.query.filter_by(Name=name).first()
        if existing_tag:
            flash('Nhãn này đã tồn tại!', 'error')
            return redirect(url_for('tags.add_tag'))
        
        # Tạo nhãn mới
        new_tag = Tag(Name=name)
        db.session.add(new_tag)
        db.session.commit()
        
        flash('Thêm nhãn thành công!', 'success')
        return redirect(url_for('tags.list_tags'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thêm nhãn: {str(e)}', 'error')
        return redirect(url_for('tags.add_tag'))


@bp.route('/admin/tags/<int:tag_id>/edit')
def edit_tag(tag_id):
    """Trang chỉnh sửa nhãn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    tag = Tag.query.get_or_404(tag_id)
    return render_template('backend/pages/tags/edit.html', tag=tag)


@bp.route('/admin/tags/<int:tag_id>/edit', methods=['POST'])
def update_tag(tag_id):
    """Cập nhật nhãn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        tag = Tag.query.get_or_404(tag_id)
        name = request.form.get('name')
        
        if not name:
            flash('Vui lòng nhập tên nhãn!', 'error')
            return redirect(url_for('tags.edit_tag', tag_id=tag_id))
        
        # Kiểm tra nhãn đã tồn tại chưa (trừ nhãn hiện tại)
        existing_tag = Tag.query.filter(Tag.Name == name, Tag.TagID != tag_id).first()
        if existing_tag:
            flash('Nhãn này đã tồn tại!', 'error')
            return redirect(url_for('tags.edit_tag', tag_id=tag_id))
        
        # Cập nhật nhãn
        tag.Name = name
        db.session.commit()
        
        flash('Cập nhật nhãn thành công!', 'success')
        return redirect(url_for('tags.list_tags'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật nhãn: {str(e)}', 'error')
        return redirect(url_for('tags.edit_tag', tag_id=tag_id))


@bp.route('/admin/tags/<int:tag_id>/delete', methods=['POST'])
def delete_tag(tag_id):
    """Xóa nhãn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        tag = Tag.query.get_or_404(tag_id)
        
        # Xóa tất cả liên kết với sản phẩm
        ProductTag.query.filter_by(TagID=tag_id).delete()
        
        # Xóa nhãn
        db.session.delete(tag)
        db.session.commit()
        
        flash('Xóa nhãn thành công!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa nhãn: {str(e)}', 'error')
    
    return redirect(url_for('tags.list_tags'))


@bp.route('/admin/tags/<int:tag_id>/products')
def tag_products(tag_id):
    """Xem sản phẩm có nhãn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    tag = Tag.query.get_or_404(tag_id)
    
    # Lấy tất cả sản phẩm có nhãn này
    products = db.session.query(Product).join(ProductTag).filter(ProductTag.TagID == tag_id).all()
    
    return render_template('backend/pages/tags/products.html', tag=tag, products=products)