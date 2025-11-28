from flask import Blueprint, render_template, request, redirect, url_for, session, current_app, flash
from werkzeug.security import generate_password_hash, check_password_hash

from config.database import db
from models import User


bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'], endpoint='login')
def user_login():
    if request.method == 'GET':
        return render_template('frontend/pages/login.html')

    # POST
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash('Vui lòng nhập đầy đủ thông tin')
        return render_template('frontend/pages/login.html')

    user: User | None = User.query.filter_by(Name=username, IsDelete=False, Role='user').first()
    if not user or not check_password_hash(user.PasswordHash, password):
        flash('Tên đăng nhập hoặc mật khẩu không đúng')
        return render_template('frontend/pages/login.html')

    session['user_id'] = user.UserID
    session['user_name'] = user.Name
    session['is_admin'] = False
    return redirect(url_for('main.home'))


@bp.route('/register', methods=['GET', 'POST'], endpoint='register')
def user_register():
    if request.method == 'GET':
        return render_template('frontend/pages/register.html')

    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    re_password = request.form.get('re_password', '').strip()

    if not username or not email or not password or not re_password:
        flash('Vui lòng nhập đầy đủ thông tin')
        return render_template('frontend/pages/register.html')

    if password != re_password:
        flash('Mật khẩu nhập lại không khớp')
        return render_template('frontend/pages/register.html')

    # Check duplicates
    if User.query.filter((User.Name == username) | (User.Email == email)).first():
        flash('Tên đăng nhập hoặc email đã tồn tại')
        return render_template('frontend/pages/register.html')

    user = User(
        Name=username,
        Email=email,
        PasswordHash=generate_password_hash(password),
        Role='user',
        IsDelete=False,
    )
    db.session.add(user)
    db.session.commit()

    flash('Đăng ký thành công. Vui lòng đăng nhập.')
    return redirect(url_for('auth.login'))


@bp.route('/admin/login', methods=['GET', 'POST'], endpoint='dashboard_login')
def admin_login():
    if request.method == 'GET':
        return render_template('backend/pages/login.html')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash('Vui lòng nhập đầy đủ thông tin')
        return render_template('backend/pages/login.html')

    # Authenticate admin user from database
    admin_user: User | None = User.query.filter_by(Name=username, IsDelete=False, Role='admin').first()
    if not admin_user or not check_password_hash(admin_user.PasswordHash, password):
        flash('Thông tin đăng nhập quản trị không đúng')
        return render_template('backend/pages/login.html')

    session['is_admin'] = True
    session['admin_username'] = admin_user.Name
    session['admin_id'] = admin_user.UserID
    session['user_id'] = admin_user.UserID
    return redirect(url_for('main.dashboard'))


@bp.route('/logout', methods=['POST'], endpoint='logout')
def logout():
    """Đăng xuất người dùng thường"""
    session.clear()
    flash('Đã đăng xuất thành công!', 'success')
    return redirect(url_for('auth.login'))


@bp.route('/admin/logout', methods=['POST'], endpoint='admin_logout')
def admin_logout():
    """Đăng xuất admin"""
    session.clear()
    flash('Đã đăng xuất thành công!', 'success')
    return redirect(url_for('auth.home'))


@bp.route('/logout', methods=['GET'], endpoint='logout_get')
def logout_get():
    """Đăng xuất người dùng thường (GET request)"""
    session.clear()
    flash('Đã đăng xuất thành công!', 'success')
    return redirect(url_for('main.home'))


@bp.route('/admin/logout', methods=['GET'], endpoint='admin_logout_get')
def admin_logout_get():
    """Đăng xuất admin (GET request)"""
    session.clear()
    flash('Đã đăng xuất thành công!', 'success')
    return redirect(url_for('main.home'))

