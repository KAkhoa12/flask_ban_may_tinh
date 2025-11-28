from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from models.tables import PcOptionGroup, PcOptionItem, Product, Category, Brand
from config.database import db
import os
import uuid
from werkzeug.utils import secure_filename

bp = Blueprint('build_pc', __name__)


@bp.route('/admin/build-pc')
def list_pc_configs():
    """Hiển thị danh sách nhóm lựa chọn PC"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy tất cả nhóm lựa chọn PC
    option_groups = PcOptionGroup.query.all()
    
    # Lấy tất cả sản phẩm linh kiện (không phải PC) để thêm vào nhóm
    components = Product.query.filter_by(IsPC=0).all()
    
    return render_template('backend/pages/build_pc/list.html', 
                         option_groups=option_groups,
                         components=components)


@bp.route('/admin/build-pc/add-group', methods=['POST'])
def add_option_group():
    """Thêm nhóm lựa chọn mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    
    if not name:
        flash('Tên nhóm lựa chọn không được để trống', 'error')
        return redirect(url_for('build_pc.list_pc_configs'))
    
    try:
        new_group = PcOptionGroup(
            Name=name,
            Description=description
        )
        db.session.add(new_group)
        db.session.commit()
        flash('Thêm nhóm lựa chọn thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thêm nhóm lựa chọn: {str(e)}', 'error')
    
    return redirect(url_for('build_pc.list_pc_configs'))


@bp.route('/admin/build-pc/edit-group/<int:group_id>', methods=['POST'])
def edit_option_group(group_id):
    """Cập nhật nhóm lựa chọn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    option_group = PcOptionGroup.query.get_or_404(group_id)
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    
    if not name:
        flash('Tên nhóm lựa chọn không được để trống', 'error')
        return redirect(url_for('build_pc.list_pc_configs'))
    
    try:
        option_group.Name = name
        option_group.Description = description
        db.session.commit()
        flash('Cập nhật nhóm lựa chọn thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật nhóm lựa chọn: {str(e)}', 'error')
    
    return redirect(url_for('build_pc.list_pc_configs'))


@bp.route('/admin/build-pc/delete-group/<int:group_id>', methods=['POST'])
def delete_option_group(group_id):
    """Xóa nhóm lựa chọn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    option_group = PcOptionGroup.query.get_or_404(group_id)
    
    try:
        # Xóa tất cả option items trong group trước
        PcOptionItem.query.filter_by(OptionGroupID=group_id).delete()
        
        # Xóa group
        db.session.delete(option_group)
        db.session.commit()
        flash('Xóa nhóm lựa chọn thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa nhóm lựa chọn: {str(e)}', 'error')
    
    return redirect(url_for('build_pc.list_pc_configs'))


@bp.route('/admin/build-pc/<int:group_id>/add-item', methods=['POST'])
def add_option_item(group_id):
    """Thêm linh kiện vào nhóm lựa chọn"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    option_group = PcOptionGroup.query.get_or_404(group_id)
    
    component_id = request.form.get('component_id')
    is_default = request.form.get('is_default', 0)
    
    if not component_id:
        flash('Vui lòng chọn linh kiện', 'error')
        return redirect(url_for('build_pc.list_pc_configs'))
    
    # Kiểm tra xem component đã tồn tại trong group chưa
    existing_item = PcOptionItem.query.filter_by(
        OptionGroupID=group_id,
        ProductID=component_id
    ).first()
    
    if existing_item:
        flash('Linh kiện này đã tồn tại trong nhóm', 'error')
        return redirect(url_for('build_pc.list_pc_configs'))
    
    try:
        new_item = PcOptionItem(
            OptionGroupID=group_id,
            ProductID=int(component_id),
            IsDefault=int(is_default)
        )
        db.session.add(new_item)
        db.session.commit()
        flash('Thêm linh kiện vào nhóm thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thêm linh kiện: {str(e)}', 'error')
    
    return redirect(url_for('build_pc.list_pc_configs'))


@bp.route('/admin/build-pc/<int:group_id>/delete-item/<int:item_id>', methods=['POST'])
def delete_option_item(group_id, item_id):
    """Xóa linh kiện khỏi nhóm"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    option_item = PcOptionItem.query.get_or_404(item_id)
    
    # Kiểm tra xem item có thuộc về group này không
    if option_item.OptionGroupID != group_id:
        flash('Không tìm thấy linh kiện', 'error')
        return redirect(url_for('build_pc.list_pc_configs'))
    
    try:
        db.session.delete(option_item)
        db.session.commit()
        flash('Xóa linh kiện khỏi nhóm thành công', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa linh kiện: {str(e)}', 'error')
    
    return redirect(url_for('build_pc.list_pc_configs'))

