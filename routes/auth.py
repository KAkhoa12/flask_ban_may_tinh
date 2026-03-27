import json
from datetime import datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import inspect
from werkzeug.security import check_password_hash, generate_password_hash

from config.database import db
from models import User
from models.tables import ChatMessage

bp = Blueprint("auth", __name__)


def _ensure_chat_table():
    inspector = inspect(db.engine)
    if ChatMessage.__tablename__ not in inspector.get_table_names():
        ChatMessage.__table__.create(bind=db.engine, checkfirst=True)


def _migrate_guest_chat_to_user(user_id: int) -> None:
    guest_history = session.get("guest_chat_history", [])
    if not guest_history:
        session.pop("chatbot_pending_action", None)
        return

    _ensure_chat_table()

    rows = []
    for item in guest_history:
        sender = (item.get("sender") or "").lower()
        role = "user" if sender == "user" else "assistant"
        text = (item.get("text") or "").strip()
        if not text:
            continue
        metadata = None
        if role == "assistant":
            metadata = json.dumps(
                {"products": item.get("sources") or []}, ensure_ascii=False
            )
        rows.append(
            ChatMessage(
                UserID=user_id,
                Role=role,
                Message=text,
                Metadata=metadata,
                CreatedAt=datetime.utcnow(),
            )
        )

    if rows:
        db.session.add_all(rows)
        db.session.commit()

    session.pop("guest_chat_history", None)
    session.pop("chatbot_pending_action", None)


@bp.route("/login", methods=["GET", "POST"], endpoint="login")
def user_login():
    if request.method == "GET":
        return render_template("frontend/pages/login.html")

    # POST
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Vui lòng nhập đầy đủ thông tin")
        return render_template("frontend/pages/login.html")

    user: User | None = User.query.filter_by(
        Name=username, IsDelete=False, Role="user"
    ).first()
    if not user or not check_password_hash(user.PasswordHash, password):
        flash("Tên đăng nhập hoặc mật khẩu không đúng")
        return render_template("frontend/pages/login.html")

    session["user_id"] = user.UserID
    session["user_name"] = user.Name
    session["is_admin"] = False
    _migrate_guest_chat_to_user(user.UserID)
    return redirect(url_for("main.home"))


@bp.route("/register", methods=["GET", "POST"], endpoint="register")
def user_register():
    if request.method == "GET":
        return render_template("frontend/pages/register.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    re_password = request.form.get("re_password", "").strip()

    if not username or not email or not password or not re_password:
        flash("Vui lòng nhập đầy đủ thông tin")
        return render_template("frontend/pages/register.html")

    if password != re_password:
        flash("Mật khẩu nhập lại không khớp")
        return render_template("frontend/pages/register.html")

    # Check duplicates
    if User.query.filter((User.Name == username) | (User.Email == email)).first():
        flash("Tên đăng nhập hoặc email đã tồn tại")
        return render_template("frontend/pages/register.html")

    user = User(
        Name=username,
        Email=email,
        PasswordHash=generate_password_hash(password),
        Role="user",
        IsDelete=False,
    )
    db.session.add(user)
    db.session.commit()

    flash("Đăng ký thành công. Vui lòng đăng nhập.")
    return redirect(url_for("auth.login"))


@bp.route("/admin/login", methods=["GET", "POST"], endpoint="dashboard_login")
def admin_login():
    if request.method == "GET":
        return render_template("backend/pages/login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Vui lòng nhập đầy đủ thông tin")
        return render_template("backend/pages/login.html")

    # Authenticate admin user from database
    admin_user: User | None = User.query.filter_by(
        Name=username, IsDelete=False, Role="admin"
    ).first()
    if not admin_user or not check_password_hash(admin_user.PasswordHash, password):
        flash("Thông tin đăng nhập quản trị không đúng")
        return render_template("backend/pages/login.html")

    session["is_admin"] = True
    session["admin_username"] = admin_user.Name
    session["admin_id"] = admin_user.UserID
    session["user_id"] = admin_user.UserID
    _migrate_guest_chat_to_user(admin_user.UserID)
    return redirect(url_for("main.dashboard"))


@bp.route("/logout", methods=["POST"], endpoint="logout")
def logout():
    """Đăng xuất người dùng thường"""
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("auth.login"))


@bp.route("/admin/logout", methods=["POST"], endpoint="admin_logout")
def admin_logout():
    """Đăng xuất admin"""
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("auth.home"))


@bp.route("/logout", methods=["GET"], endpoint="logout_get")
def logout_get():
    """Đăng xuất người dùng thường (GET request)"""
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("main.home"))


@bp.route("/admin/logout", methods=["GET"], endpoint="admin_logout_get")
def admin_logout_get():
    """Đăng xuất admin (GET request)"""
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("main.home"))
