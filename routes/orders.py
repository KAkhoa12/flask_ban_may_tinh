from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models.tables import Order, OrderDetail, User, Product
from config.database import db
from datetime import datetime

bp = Blueprint('orders', __name__)


@bp.route('/admin/orders')
def list_orders():
    """Danh sách đơn hàng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy tất cả đơn hàng với thông tin user
    orders = db.session.query(Order).join(User).filter(User.IsDelete == False).order_by(Order.CreatedAt.desc()).all()
    return render_template('backend/pages/orders/list.html', orders=orders)


@bp.route('/admin/orders/<int:order_id>')
def detail_order(order_id):
    """Chi tiết đơn hàng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Lấy đơn hàng với thông tin user
    order = db.session.query(Order).join(User).filter(
        Order.OrderID == order_id,
        User.IsDelete == False
    ).first_or_404()
    
    # Lấy chi tiết đơn hàng với thông tin sản phẩm
    order_details = db.session.query(OrderDetail).join(Product).filter(
        OrderDetail.OrderID == order_id
    ).all()
    
    return render_template('backend/pages/orders/detail.html', order=order, order_details=order_details)


@bp.route('/admin/orders/<int:order_id>/update-status', methods=['POST'])
def update_order_status(order_id):
    """Cập nhật trạng thái đơn hàng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    try:
        order = Order.query.get_or_404(order_id)
        new_status = request.form.get('status')
        
        if new_status not in ['pending', 'processing', 'completed', 'cancelled']:
            flash('Trạng thái không hợp lệ!', 'error')
            return redirect(url_for('orders.detail_order', order_id=order_id))
        
        order.Status = new_status
        db.session.commit()
        
        flash('Cập nhật trạng thái đơn hàng thành công!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi cập nhật trạng thái: {str(e)}', 'error')
    
    return redirect(url_for('orders.detail_order', order_id=order_id))


@bp.route('/admin/orders/statistics')
def order_statistics():
    """Thống kê đơn hàng"""
    if not session.get('is_admin'):
        return redirect(url_for('auth.dashboard_login'))
    
    # Thống kê tổng quan
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(Status='pending').count()
    processing_orders = Order.query.filter_by(Status='processing').count()
    completed_orders = Order.query.filter_by(Status='completed').count()
    cancelled_orders = Order.query.filter_by(Status='cancelled').count()
    
    # Tổng doanh thu
    total_revenue = db.session.query(db.func.sum(Order.TotalPrice)).filter_by(Status='completed').scalar() or 0
    
    # Đơn hàng theo tháng (6 tháng gần nhất)
    from sqlalchemy import extract
    current_date = datetime.now()
    monthly_orders = []
    
    for i in range(6):
        month = current_date.month - i
        year = current_date.year
        if month <= 0:
            month += 12
            year -= 1
        
        count = Order.query.filter(
            extract('year', Order.CreatedAt) == year,
            extract('month', Order.CreatedAt) == month
        ).count()
        
        monthly_orders.append({
            'month': f"{month:02d}/{year}",
            'count': count
        })
    
    monthly_orders.reverse()
    
    return render_template('backend/pages/orders/statistics.html',
                         total_orders=total_orders,
                         pending_orders=pending_orders,
                         processing_orders=processing_orders,
                         completed_orders=completed_orders,
                         cancelled_orders=cancelled_orders,
                         total_revenue=total_revenue,
                         monthly_orders=monthly_orders)