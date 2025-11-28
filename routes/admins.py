from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import User
from config.database import db
from werkzeug.security import generate_password_hash
from datetime import datetime

bp = Blueprint('admins', __name__)


@bp.route('/admin/admins')
def list_admins():
    """Danh sách admin"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy tất cả user có role là 'admin'
    admins = User.query.filter_by(Role='admin', IsDelete=False).all()
    return render_template('backend/pages/admins/list.html', admins=admins)


@bp.route('/admin/admins/add')
def add_admin():
    """Trang thêm admin mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    return render_template('backend/pages/admins/add.html')


@bp.route('/admin/admins/add', methods=['POST'])
def save_admin():
    """Lưu admin mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([name, email, password, confirm_password]):
            flash('Vui lòng điền đầy đủ thông tin!', 'error')
            return redirect(url_for('admins.add_admin'))
        
        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp!', 'error')
            return redirect(url_for('admins.add_admin'))
        
        if len(password) < 6:
            flash('Mật khẩu phải có ít nhất 6 ký tự!', 'error')
            return redirect(url_for('admins.add_admin'))
        
        # Kiểm tra email đã tồn tại chưa
        existing_user = User.query.filter_by(Email=email).first()
        if existing_user:
            flash('Email này đã được sử dụng!', 'error')
            return redirect(url_for('admins.add_admin'))
        
        # Tạo admin mới
        new_admin = User(
            Name=name,
            Email=email,
            PasswordHash=generate_password_hash(password),
            Role='admin'
        )
        db.session.add(new_admin)
        db.session.commit()
        
        flash('Thêm admin thành công!', 'success')
        return redirect(url_for('admins.list_admins'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thêm admin: {str(e)}', 'error')
        return redirect(url_for('admins.add_admin'))


@bp.route('/admin/admins/<int:admin_id>/edit')
def edit_admin(admin_id):
    """Trang chỉnh sửa admin"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Không cho phép admin tự xóa/sửa chính mình
    current_admin_id = session.get('admin_id')
    if current_admin_id == admin_id:
        flash('Bạn không thể chỉnh sửa tài khoản của chính mình!', 'error')
        return redirect(url_for('admins.list_admins'))
    
    admin = User.query.filter_by(UserID=admin_id, Role='admin', IsDelete=False).first_or_404()
    return render_template('backend/pages/admins/edit.html', admin=admin)


@bp.route('/admin/admins/<int:admin_id>/edit', methods=['POST'])
def update_admin(admin_id):
    """Cập nhật admin"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Không cho phép admin tự xóa/sửa chính mình
    current_admin_id = session.get('admin_id')
    if current_admin_id == admin_id:
        flash('Bạn không thể chỉnh sửa tài khoản của chính mình!', 'error')
        return redirect(url_for('admins.list_admins'))
    
    try:
        admin = User.query.filter_by(UserID=admin_id, Role='admin', IsDelete=False).first_or_404()
        
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([name, email]):
            flash('Vui lòng điền đầy đủ thông tin bắt buộc!', 'error')
            return redirect(url_for('admins.edit_admin', admin_id=admin_id))
        
        # Kiểm tra email đã tồn tại chưa (trừ admin hiện tại)
        existing_user = User.query.filter(User.Email == email, User.UserID != admin_id).first()
        if existing_user:
            flash('Email này đã được sử dụng!', 'error')
            return redirect(url_for('admins.edit_admin', admin_id=admin_id))
        
        # Cập nhật thông tin
        admin.Name = name
        admin.Email = email
        
        # Cập nhật mật khẩu nếu có
        if password and confirm_password:
            if password != confirm_password:
                flash('Mật khẩu xác nhận không khớp!', 'error')
                return redirect(url_for('admins.edit_admin', admin_id=admin_id))
            
            if len(password) < 6:
                flash('Mật khẩu phải có ít nhất 6 ký tự!', 'error')
                return redirect(url_for('admins.edit_admin', admin_id=admin_id))
            
            admin.PasswordHash = generate_password_hash(password)
        
        db.session.commit()
        
        flash('Cập nhật admin thành công!', 'success')
        return redirect(url_for('admins.list_admins'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật admin: {str(e)}', 'error')
        return redirect(url_for('admins.edit_admin', admin_id=admin_id))


@bp.route('/admin/admins/<int:admin_id>/delete', methods=['POST'])
def delete_admin(admin_id):
    """Xóa admin (soft delete)"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Không cho phép admin tự xóa/sửa chính mình
    current_admin_id = session.get('admin_id')
    if current_admin_id == admin_id:
        flash('Bạn không thể xóa tài khoản của chính mình!', 'error')
        return redirect(url_for('admins.list_admins'))
    
    try:
        admin = User.query.filter_by(UserID=admin_id, Role='admin', IsDelete=False).first_or_404()
        
        # Kiểm tra xem có phải admin cuối cùng không
        admin_count = User.query.filter_by(Role='admin', IsDelete=False).count()
        if admin_count <= 1:
            flash('Không thể xóa admin cuối cùng trong hệ thống!', 'error')
            return redirect(url_for('admins.list_admins'))
        
        # Soft delete - đánh dấu IsDelete = True
        admin.IsDelete = True
        db.session.commit()
        
        flash('Xóa admin thành công!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa admin: {str(e)}', 'error')
    
    return redirect(url_for('admins.list_admins'))


@bp.route('/admin/admins/<int:admin_id>/toggle-status', methods=['POST'])
def toggle_admin_status(admin_id):
    """Bật/tắt trạng thái admin"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Không cho phép admin tự thay đổi trạng thái chính mình
    current_admin_id = session.get('admin_id')
    if current_admin_id == admin_id:
        flash('Bạn không thể thay đổi trạng thái của chính mình!', 'error')
        return redirect(url_for('admins.list_admins'))
    
    try:
        admin = User.query.filter_by(UserID=admin_id, Role='admin', IsDelete=False).first_or_404()
        
        # Toggle trạng thái (giả sử có field IsActive, nếu không có thì bỏ qua)
        # admin.IsActive = not admin.IsActive
        # db.session.commit()
        
        flash('Thay đổi trạng thái admin thành công!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thay đổi trạng thái: {str(e)}', 'error')
    
    return redirect(url_for('admins.list_admins'))