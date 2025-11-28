from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import User, Order
from config.database import db
from werkzeug.security import generate_password_hash
from datetime import datetime

bp = Blueprint('users', __name__)


@bp.route('/admin/users')
def list_users():
    """Danh sách người dùng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy tất cả người dùng có role là 'user'
    users = User.query.filter_by(Role='user', IsDelete=False).all()
    return render_template('backend/pages/users/list.html', users=users)


@bp.route('/admin/users/add')
def add_user():
    """Trang thêm người dùng mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    return render_template('backend/pages/users/add.html')


@bp.route('/admin/users/add', methods=['POST'])
def save_user():
    """Lưu người dùng mới"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([name, email, password, confirm_password]):
            flash('Vui lòng điền đầy đủ thông tin!', 'error')
            return redirect(url_for('users.add_user'))
        
        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp!', 'error')
            return redirect(url_for('users.add_user'))
        
        # Kiểm tra email đã tồn tại chưa
        existing_user = User.query.filter_by(Email=email).first()
        if existing_user:
            flash('Email này đã được sử dụng!', 'error')
            return redirect(url_for('users.add_user'))
        
        # Tạo người dùng mới
        new_user = User(
            Name=name,
            Email=email,
            PasswordHash=generate_password_hash(password),
            Role='user'
        )
        db.session.add(new_user)
        db.session.commit()
        
        flash('Thêm người dùng thành công!', 'success')
        return redirect(url_for('users.list_users'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi thêm người dùng: {str(e)}', 'error')
        return redirect(url_for('users.add_user'))


@bp.route('/admin/users/<int:user_id>/edit')
def edit_user(user_id):
    """Trang chỉnh sửa người dùng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    user = User.query.filter_by(UserID=user_id, Role='user', IsDelete=False).first_or_404()
    return render_template('backend/pages/users/edit.html', user=user)


@bp.route('/admin/users/<int:user_id>/edit', methods=['POST'])
def update_user(user_id):
    """Cập nhật người dùng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        user = User.query.filter_by(UserID=user_id, Role='user', IsDelete=False).first_or_404()
        
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([name, email]):
            flash('Vui lòng điền đầy đủ thông tin bắt buộc!', 'error')
            return redirect(url_for('users.edit_user', user_id=user_id))
        
        # Kiểm tra email đã tồn tại chưa (trừ user hiện tại)
        existing_user = User.query.filter(User.Email == email, User.UserID != user_id).first()
        if existing_user:
            flash('Email này đã được sử dụng!', 'error')
            return redirect(url_for('users.edit_user', user_id=user_id))
        
        # Cập nhật thông tin
        user.Name = name
        user.Email = email
        
        # Cập nhật mật khẩu nếu có
        if password and confirm_password:
            if password != confirm_password:
                flash('Mật khẩu xác nhận không khớp!', 'error')
                return redirect(url_for('users.edit_user', user_id=user_id))
            user.PasswordHash = generate_password_hash(password)
        
        db.session.commit()
        
        flash('Cập nhật người dùng thành công!', 'success')
        return redirect(url_for('users.list_users'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật người dùng: {str(e)}', 'error')
        return redirect(url_for('users.edit_user', user_id=user_id))


@bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    """Xóa người dùng (soft delete)"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        user = User.query.filter_by(UserID=user_id, Role='user', IsDelete=False).first_or_404()
        
        # Soft delete - đánh dấu IsDelete = True
        user.IsDelete = True
        db.session.commit()
        
        flash('Xóa người dùng thành công!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa người dùng: {str(e)}', 'error')
    
    return redirect(url_for('users.list_users'))


@bp.route('/admin/users/<int:user_id>/orders')
def user_orders(user_id):
    """Xem đơn hàng của người dùng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    user = User.query.filter_by(UserID=user_id, Role='user', IsDelete=False).first_or_404()
    
    # Lấy tất cả đơn hàng của user
    orders = Order.query.filter_by(UserID=user_id).order_by(Order.CreatedAt.desc()).all()
    
    return render_template('backend/pages/users/orders.html', user=user, orders=orders)