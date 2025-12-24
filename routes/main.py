import json
import os
import uuid
from datetime import datetime

from config.database import DatabaseConfig, db
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from models.tables import (
    Brand,
    Cart,
    CartDetail,
    Category,
    Order,
    OrderDetail,
    PcOptionGroup,
    PcOptionItem,
    Product,
    ProductTag,
    Tag,
    User,
)
from sqlalchemy import func

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    # Lấy 10 sản phẩm linh kiện mới nhất
    products_early = (
        Product.query.filter_by(IsPC=False)
        .order_by(Product.CreatedAt.desc())
        .limit(10)
        .all()
    )

    # Lấy 10 sản phẩm PC mới nhất
    pc_products = (
        Product.query.filter_by(IsPC=True)
        .order_by(Product.CreatedAt.desc())
        .limit(10)
        .all()
    )

    # Lấy 10 linh kiện bán chạy nhất
    top_selling_components_query = (
        db.session.query(
            Product, func.sum(OrderDetail.Quantity).label("total_quantity")
        )
        .join(OrderDetail, Product.ProductID == OrderDetail.ProductID)
        .filter(Product.IsPC == False)
        .group_by(Product.ProductID)
        .order_by(func.sum(OrderDetail.Quantity).desc())
        .limit(10)
        .all()
    )
    top_selling_components = [
        product for product, quantity in top_selling_components_query
    ]

    # Lấy 10 PC bán chạy nhất
    top_selling_pcs_query = (
        db.session.query(
            Product, func.sum(OrderDetail.Quantity).label("total_quantity")
        )
        .join(OrderDetail, Product.ProductID == OrderDetail.ProductID)
        .filter(Product.IsPC == True)
        .group_by(Product.ProductID)
        .order_by(func.sum(OrderDetail.Quantity).desc())
        .limit(10)
        .all()
    )
    top_selling_pcs = [product for product, quantity in top_selling_pcs_query]

    return render_template(
        "frontend/pages/homepage.html",
        products_early=products_early,
        pc_products=pc_products,
        top_selling_components=top_selling_components,
        top_selling_pcs=top_selling_pcs,
    )


@bp.route("/pc-products")
def pc_products():
    # Lấy category có name là "PC"
    pc_parent = Category.query.filter_by(Name="PC").first()

    if not pc_parent:
        flash("Không tìm thấy danh mục PC", "error")
        return redirect(url_for("main.home"))

    # Lấy các category con của PC
    pc_categories = Category.query.filter_by(ParentID=pc_parent.CategoryID).all()

    # Lấy tất cả sản phẩm PC (IsPC = 1)
    pc_products = Product.query.filter_by(IsPC=1).all()

    # Lấy danh sách brands cho filter
    brands = Brand.query.all()

    return render_template(
        "frontend/pages/pc_products.html",
        pc_categories=pc_categories,
        pc_products=pc_products,
        brands=brands,
    )


@bp.route("/linhkien-products")
def linhkien_products():
    # Lấy category có name là "PC"
    pc_parent = Category.query.filter_by(Name="PC").first()

    # Lấy tất cả category con của PC (để loại trừ)
    pc_child_categories = []
    if pc_parent:
        pc_child_categories = Category.query.filter_by(
            ParentID=pc_parent.CategoryID
        ).all()
        pc_child_category_ids = [cat.CategoryID for cat in pc_child_categories]
    else:
        pc_child_category_ids = []

    # Lấy tất cả linh kiện, loại trừ:
    # 1. Sản phẩm có Name = "pc"
    # 2. Sản phẩm có IsPC = 1
    # 3. Sản phẩm thuộc category con của PC
    query = Product.query.filter(Product.Name != "pc", Product.IsPC == 0)

    # Loại trừ sản phẩm thuộc category con của PC
    if pc_child_category_ids:
        query = query.filter(~Product.CategoryID.in_(pc_child_category_ids))

    linhkien_products = query.all()

    # Lấy tất cả categories (trừ PC và con của PC) để filter
    all_categories = Category.query.filter(Category.Name != "PC").all()

    if pc_child_category_ids:
        all_categories = [
            cat for cat in all_categories if cat.CategoryID not in pc_child_category_ids
        ]

    # Lấy danh sách brands cho filter
    brands = Brand.query.all()

    return render_template(
        "frontend/pages/linhkien_products.html",
        linhkien_products=linhkien_products,
        categories=all_categories,
        brands=brands,
    )


@bp.route("/advisor")
def advisor_page():
    """Trang tư vấn gợi ý lựa chọn cấu hình PC dựa trên Tag"""
    tags = Tag.query.all()
    topic_to_values = {}
    for tag in tags:
        parts = [p.strip() for p in tag.Name.split("<>")]
        if len(parts) == 2:
            topic, value = parts
        else:
            topic, value = "Khác", tag.Name
        topic_to_values.setdefault(topic, set()).add(value)
    topic_to_values = {k: sorted(list(v)) for k, v in topic_to_values.items()}

    return render_template(
        "frontend/pages/advisor.html",
        topic_to_values=topic_to_values,
        title="Tư vấn gợi ý cấu hình PC",
    )


@bp.route("/advisor/suggest", methods=["POST"])
def advisor_suggest():
    """Trả về gợi ý PC theo danh sách tiêu chí (topic <> value)"""
    try:
        data = request.get_json(silent=True) or {}
        criteria = data.get("criteria", [])
        # Xây lại danh sách tag đầy đủ theo định dạng
        selected_tags = set()
        for c in criteria:
            topic = (c.get("topic") or "").strip()
            value = (c.get("value") or "").strip()
            if topic and value:
                selected_tags.add(f"{topic} <> {value}")

        n_selected = len(selected_tags)
        if n_selected == 0:
            return jsonify(
                {"success": False, "message": "Vui lòng chọn ít nhất một tiêu chí"}
            ), 400

        # Lấy tất cả PC và map tags cho từng PC
        pc_products = Product.query.filter_by(IsPC=1).all()
        product_id_to_tags = {}

        # Lấy ProductTag theo danh sách PC để giảm queries
        pc_ids = [p.ProductID for p in pc_products]
        if not pc_ids:
            return jsonify(
                {"success": True, "data": {"type1": [], "type2": [], "type3": []}}
            )

        product_tags = ProductTag.query.filter(ProductTag.ProductID.in_(pc_ids)).all()
        tag_id_to_name = {t.TagID: t.Name for t in Tag.query.all()}
        for pt in product_tags:
            name = tag_id_to_name.get(pt.TagID)
            if not name:
                continue
            product_id_to_tags.setdefault(pt.ProductID, set()).add(name)

        # Tính điểm khớp
        scored = []
        for p in pc_products:
            tags_of_p = product_id_to_tags.get(p.ProductID, set())
            match_count = len(tags_of_p.intersection(selected_tags))
            if match_count == 0:
                continue  # bỏ những PC không khớp tiêu chí nào
            scored.append(
                {
                    "id": p.ProductID,
                    "name": p.Name,
                    "price": p.Price,
                    "image": p.ImageURL,
                    "match_count": match_count,
                    "total_selected": n_selected,
                    "match_ratio": (match_count / n_selected) if n_selected else 0.0,
                }
            )

        # Phân loại theo tỉ lệ khớp: type1 >= 80%, type2 [40%, 80%), type3 < 40%
        import math

        high_threshold = math.ceil(0.8 * n_selected)
        mid_threshold = max(1, math.ceil(0.4 * n_selected))

        type1 = []
        type2 = []
        type3 = []
        for item in scored:
            mc = item["match_count"]
            if mc >= high_threshold:
                type1.append(item)
            elif mc >= mid_threshold:
                type2.append(item)
            else:
                type3.append(item)

        # Sắp xếp mỗi nhóm theo số match giảm dần, rồi theo giá tăng dần
        def sort_key(it):
            return (-it["match_count"], it["price"] or 0)

        type1.sort(key=sort_key)
        type2.sort(key=sort_key)
        type3.sort(key=sort_key)

        return jsonify(
            {
                "success": True,
                "data": {
                    "type1": type1,
                    "type2": type2,
                    "type3": type3,
                    "thresholds": {
                        "high_min": high_threshold,
                        "mid_min": mid_threshold,
                        "selected_count": n_selected,
                    },
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi khi gợi ý: {str(e)}"}), 500


@bp.route("/product/<int:product_id>")
def product_detail(product_id):
    """Chi tiết sản phẩm"""
    product = Product.query.get_or_404(product_id)

    # Nếu là sản phẩm PC, chuyển hướng đến trang chi tiết PC
    if product.IsPC == 1:
        return redirect(url_for("main.pc_detail", product_id=product_id))

    # Lấy category và brand của sản phẩm
    category = product.category
    brand = product.brand

    # Lấy các sản phẩm liên quan (cùng category)
    related_products = (
        Product.query.filter(
            Product.CategoryID == product.CategoryID, Product.ProductID != product_id
        )
        .limit(4)
        .all()
    )

    return render_template(
        "frontend/pages/product.html",
        product=product,
        category=category,
        brand=brand,
        products_related=related_products,
        title=f"{product.Name} - Chi tiết sản phẩm",
    )


@bp.route("/pc-detail/<int:product_id>")
def pc_detail(product_id):
    """Chi tiết sản phẩm PC với lựa chọn linh kiện"""
    # Lấy sản phẩm PC
    pc_product = Product.query.filter_by(ProductID=product_id, IsPC=1).first_or_404()

    # Lấy tất cả nhóm lựa chọn có linh kiện (đã được thêm vào PC)
    all_groups = PcOptionGroup.query.all()

    # Tạo dictionary để lưu thông tin nhóm và sản phẩm
    groups_with_products = []
    for group in all_groups:
        # Lấy tất cả sản phẩm trong nhóm này
        group_items = PcOptionItem.query.filter_by(
            OptionGroupID=group.OptionGroupID
        ).all()

        if group_items:  # Chỉ hiển thị nhóm có sản phẩm (đã được thêm vào PC)
            products_in_group = []
            for item in group_items:
                product = Product.query.get(item.ProductID)
                if product:
                    products_in_group.append(
                        {
                            "product": product,
                            "is_default": item.IsDefault,
                            "item_id": item.OptionItemID,
                        }
                    )

            # Sắp xếp để sản phẩm mặc định lên đầu
            products_in_group.sort(key=lambda x: x["is_default"], reverse=True)

            groups_with_products.append({"group": group, "products": products_in_group})

    # Lấy tags của sản phẩm hiện tại
    product_tags = ProductTag.query.filter_by(ProductID=product_id).all()
    current_tags = [
        Tag.query.get(pt.TagID) for pt in product_tags if Tag.query.get(pt.TagID)
    ]

    # Lấy tất cả tags (phục vụ admin thêm nhanh)
    all_tags = Tag.query.all()

    # Lấy các sản phẩm PC liên quan
    related_pcs = (
        Product.query.filter(Product.IsPC == 1, Product.ProductID != product_id)
        .limit(4)
        .all()
    )

    return render_template(
        "frontend/pages/pc_detail.html",
        pc_product=pc_product,
        groups_with_products=groups_with_products,
        current_tags=current_tags,
        all_tags=all_tags,
        related_pcs=related_pcs,
        title=f"{pc_product.Name} - Cấu hình PC",
    )


@bp.route("/pc-detail/<int:product_id>/add-tag", methods=["POST"])
def add_tag_to_pc(product_id):
    """Thêm tag cho sản phẩm (admin) - dùng chung cho frontend và backend"""
    if not session.get("is_admin"):
        flash("Bạn không có quyền thực hiện thao tác này", "error")
        # quay về trang phù hợp
        ref = request.referrer or ""
        if "/admin/pc/" in ref:
            return redirect(url_for("main.admin_pc_detail", product_id=product_id))
        return redirect(url_for("main.pc_detail", product_id=product_id))

    try:
        tag_id = request.form.get("tag_id")
        tag_name = request.form.get("tag_name")

        # Ưu tiên theo tag_id, nếu không có thì thử tìm theo tên
        tag = None
        if tag_id:
            tag = Tag.query.get(int(tag_id))
        elif tag_name:
            tag = Tag.query.filter_by(Name=tag_name.strip()).first()

        if not tag:
            flash("Không tìm thấy tag hợp lệ", "error")
            ref = request.referrer or ""
            if "/admin/pc/" in ref:
                return redirect(url_for("main.admin_pc_detail", product_id=product_id))
            return redirect(url_for("main.pc_detail", product_id=product_id))

        # Kiểm tra đã tồn tại liên kết chưa
        exists = ProductTag.query.filter_by(
            ProductID=product_id, TagID=tag.TagID
        ).first()
        if exists:
            flash("Tag đã tồn tại trên sản phẩm", "error")
            ref = request.referrer or ""
            if "/admin/pc/" in ref:
                return redirect(url_for("main.admin_pc_detail", product_id=product_id))
            return redirect(url_for("main.pc_detail", product_id=product_id))

        # Tạo liên kết
        db.session.add(ProductTag(ProductID=product_id, TagID=tag.TagID))
        db.session.commit()
        flash("Đã thêm tag cho sản phẩm", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi thêm tag: {str(e)}", "error")

    ref = request.referrer or ""
    if "/admin/pc/" in ref:
        return redirect(url_for("main.admin_pc_detail", product_id=product_id))
    return redirect(url_for("main.pc_detail", product_id=product_id))


@bp.route("/add-pc-to-cart", methods=["POST"])
def add_pc_to_cart():
    """Thêm PC với cấu hình linh kiện vào giỏ hàng"""
    import json

    from flask import jsonify, request

    if not session.get("user_id"):
        return jsonify(
            {
                "success": False,
                "message": "Vui lòng đăng nhập để thêm sản phẩm vào giỏ hàng",
            }
        )

    try:
        data = request.get_json()
        pc_id = data.get("pcId")
        total_price = data.get("totalPrice")
        selected_components = data.get("selectedComponents", {})

        if not pc_id or not total_price:
            return jsonify({"success": False, "message": "Thiếu thông tin sản phẩm"})

        # Lấy thông tin PC
        pc_product = Product.query.get(pc_id)
        if not pc_product or pc_product.IsPC != 1:
            return jsonify({"success": False, "message": "Sản phẩm PC không tồn tại"})

        # Tạo tên sản phẩm với cấu hình
        component_names = []
        for group_id, component in selected_components.items():
            product = Product.query.get(component["productId"])
            if product:
                component_names.append(product.Name)

        config_name = f"{pc_product.Name} ({', '.join(component_names)})"

        # Kiểm tra xem đã có giỏ hàng chưa
        user_id = session["user_id"]
        cart = Cart.query.filter_by(UserID=user_id).first()

        if not cart:
            cart = Cart(UserID=user_id)
            db.session.add(cart)
            db.session.flush()

        # Tạo config data để so sánh
        config_data = json.dumps(
            {
                "pc_name": pc_product.Name,
                "config_name": config_name,
                "selected_components": selected_components,
                "component_names": component_names,
            }
        )

        # Kiểm tra xem đã có sản phẩm với cùng cấu hình chưa
        existing_cart_detail = (
            CartDetail.query.filter_by(CartID=cart.CartID, ProductID=pc_id)
            .filter(CartDetail.ConfigData == config_data)
            .first()
        )

        if existing_cart_detail:
            # Nếu đã có, tăng số lượng
            existing_cart_detail.Quantity += 1
        else:
            # Nếu chưa có, tạo mới
            cart_detail = CartDetail(
                CartID=cart.CartID,
                ProductID=pc_id,
                Quantity=1,
                Price=total_price,
                ConfigData=config_data,
            )
            db.session.add(cart_detail)

        db.session.commit()

        return jsonify(
            {"success": True, "message": "Đã thêm PC vào giỏ hàng thành công"}
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Có lỗi xảy ra: {str(e)}"})


@bp.route("/add-to-cart/<int:product_id>", methods=["POST"])
@bp.route("/add-to-cart/<int:product_id>", methods=["GET", "POST"])
def add_to_cart(product_id):
    """Thêm sản phẩm vào giỏ hàng bằng GET hoặc POST"""
    user_id = session.get("user_id")
    if not user_id:
        flash("Vui lòng đăng nhập để thêm sản phẩm vào giỏ hàng", "error")
        return redirect(url_for("main.product_detail", product_id=product_id))

    product = Product.query.get_or_404(product_id)
    quantity = (
        int(request.form.get("quantity", 1))
        if request.method == "POST"
        else int(request.args.get("quantity", 1))
    )

    if quantity > product.Stock:
        flash("Số lượng sản phẩm không đủ trong kho", "error")
        return redirect(url_for("main.product_detail", product_id=product_id))

    cart = Cart.query.filter_by(UserID=user_id).first()
    if not cart:
        cart = Cart(UserID=user_id)
        db.session.add(cart)
        db.session.commit()

    cart_detail = CartDetail.query.filter_by(
        CartID=cart.CartID, ProductID=product_id
    ).first()
    if cart_detail:
        cart_detail.Quantity += quantity
    else:
        cart_detail = CartDetail(
            CartID=cart.CartID,
            ProductID=product_id,
            Quantity=quantity,
            Price=product.Price,
        )
        db.session.add(cart_detail)

    db.session.commit()
    flash(f"Đã thêm {quantity} {product.Name} vào giỏ hàng", "success")
    return redirect(url_for("main.product_detail", product_id=product_id))


@bp.route("/cart")
def view_cart():
    """Xem giỏ hàng"""
    if not session.get("user_id"):
        flash("Vui lòng đăng nhập để xem giỏ hàng", "error")
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    cart = Cart.query.filter_by(UserID=user_id).first()

    if not cart:
        cart_details = []
        subtotal = 0
    else:
        cart_details = CartDetail.query.filter_by(CartID=cart.CartID).all()
        subtotal = sum(detail.Price * detail.Quantity for detail in cart_details)

    return render_template(
        "frontend/pages/cart.html",
        cart_details=cart_details,
        subtotal=subtotal,
        title="Giỏ hàng",
    )


@bp.route("/increase-cart-item/<int:product_id>")
def increase_cart_item(product_id):
    """Tăng số lượng sản phẩm trong giỏ hàng"""
    from flask import jsonify

    if not session.get("user_id"):
        return jsonify({"success": False, "message": "Vui lòng đăng nhập"})

    user_id = session["user_id"]
    cart = Cart.query.filter_by(UserID=user_id).first()

    if cart:
        cart_detail = CartDetail.query.filter_by(
            CartID=cart.CartID, ProductID=product_id
        ).first()
        if cart_detail:
            cart_detail.Quantity += 1
            db.session.commit()
            return jsonify(
                {"success": True, "message": "Đã cập nhật số lượng sản phẩm"}
            )
        else:
            return jsonify(
                {"success": False, "message": "Không tìm thấy sản phẩm trong giỏ hàng"}
            )
    else:
        return jsonify({"success": False, "message": "Không tìm thấy giỏ hàng"})


@bp.route("/decrease-cart-item/<int:product_id>")
def decrease_cart_item(product_id):
    """Giảm số lượng sản phẩm trong giỏ hàng"""
    from flask import jsonify

    if not session.get("user_id"):
        return jsonify({"success": False, "message": "Vui lòng đăng nhập"})

    user_id = session["user_id"]
    cart = Cart.query.filter_by(UserID=user_id).first()

    if cart:
        cart_detail = CartDetail.query.filter_by(
            CartID=cart.CartID, ProductID=product_id
        ).first()
        if cart_detail:
            if cart_detail.Quantity > 1:
                cart_detail.Quantity -= 1
                db.session.commit()
                return jsonify(
                    {"success": True, "message": "Đã cập nhật số lượng sản phẩm"}
                )
            else:
                # Xóa sản phẩm khỏi giỏ hàng nếu số lượng = 0
                db.session.delete(cart_detail)
                db.session.commit()
                return jsonify(
                    {"success": True, "message": "Đã xóa sản phẩm khỏi giỏ hàng"}
                )
        else:
            return jsonify(
                {"success": False, "message": "Không tìm thấy sản phẩm trong giỏ hàng"}
            )
    else:
        return jsonify({"success": False, "message": "Không tìm thấy giỏ hàng"})


@bp.route("/remove-from-cart/<int:product_id>")
def remove_from_cart(product_id):
    """Xóa sản phẩm khỏi giỏ hàng"""
    from flask import jsonify

    if not session.get("user_id"):
        return jsonify({"success": False, "message": "Vui lòng đăng nhập"})

    user_id = session["user_id"]
    cart = Cart.query.filter_by(UserID=user_id).first()

    if cart:
        cart_detail = CartDetail.query.filter_by(
            CartID=cart.CartID, ProductID=product_id
        ).first()
        if cart_detail:
            db.session.delete(cart_detail)
            db.session.commit()
            return jsonify(
                {"success": True, "message": "Đã xóa sản phẩm khỏi giỏ hàng"}
            )
        else:
            return jsonify(
                {"success": False, "message": "Không tìm thấy sản phẩm trong giỏ hàng"}
            )
    else:
        return jsonify({"success": False, "message": "Không tìm thấy giỏ hàng"})


@bp.route("/checkout")
def checkout():
    """Trang thanh toán"""
    if not session.get("user_id"):
        flash("Vui lòng đăng nhập để thanh toán", "error")
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    cart = Cart.query.filter_by(UserID=user_id).first()

    if not cart:
        flash("Giỏ hàng trống", "error")
        return redirect(url_for("main.view_cart"))

    cart_details = CartDetail.query.filter_by(CartID=cart.CartID).all()
    if not cart_details:
        flash("Giỏ hàng trống", "error")
        return redirect(url_for("main.view_cart"))

    subtotal = sum(detail.Price * detail.Quantity for detail in cart_details)

    return render_template(
        "frontend/pages/checkout.html",
        cart_details=cart_details,
        subtotal=subtotal,
        title="Thanh toán",
    )


@bp.route("/process-cod-payment", methods=["POST"])
def process_cod_payment():
    if not session.get("user_id"):
        return jsonify(
            {"success": False, "message": "Vui lòng đăng nhập để thanh toán"}
        )

    try:
        user_id = session["user_id"]

        # Lấy thông tin giỏ hàng
        cart = Cart.query.filter_by(UserID=user_id).first()
        if not cart:
            return jsonify({"success": False, "message": "Giỏ hàng trống"})

        cart_details = CartDetail.query.filter_by(CartID=cart.CartID).all()
        if not cart_details:
            return jsonify({"success": False, "message": "Giỏ hàng trống"})

        # Tính tổng tiền
        total_price = sum(detail.Price * detail.Quantity for detail in cart_details)

        # Tạo đơn hàng mới
        new_order = Order(UserID=user_id, TotalPrice=total_price, Status="Chờ xử lý")
        db.session.add(new_order)
        db.session.flush()  # Để lấy OrderID

        # Tạo OrderDetail từ CartDetail
        for cart_detail in cart_details:
            order_detail = OrderDetail(
                OrderID=new_order.OrderID,
                ProductID=cart_detail.ProductID,
                Quantity=cart_detail.Quantity,
                Price=cart_detail.Price,
                ConfigData=cart_detail.ConfigData,  # Copy ConfigData từ CartDetail
            )
            db.session.add(order_detail)

        # Xóa giỏ hàng sau khi tạo đơn hàng thành công
        for cart_detail in cart_details:
            db.session.delete(cart_detail)
        db.session.delete(cart)

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Đơn hàng đã được tạo thành công!",
                "order_id": new_order.OrderID,
                "total_price": total_price,
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Có lỗi xảy ra: {str(e)}"})


@bp.route("/profile")
def user_profile():
    """Trang thông tin người dùng"""
    if not session.get("user_id"):
        flash("Vui lòng đăng nhập để xem thông tin", "error")
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    user = User.query.get(user_id)

    if not user:
        flash("Không tìm thấy thông tin người dùng", "error")
        return redirect(url_for("auth.login"))

    # Lấy thống kê đơn hàng
    orders = Order.query.filter_by(UserID=user_id).all()
    total_orders = len(orders)
    total_spent = sum(order.TotalPrice for order in orders)

    return render_template(
        "frontend/pages/profile.html",
        user=user,
        total_orders=total_orders,
        total_spent=total_spent,
        title="Thông tin cá nhân",
    )


@bp.route("/order-history")
def order_history():
    """Trang lịch sử mua hàng"""
    if not session.get("user_id"):
        flash("Vui lòng đăng nhập để xem lịch sử mua hàng", "error")
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    orders = (
        Order.query.filter_by(UserID=user_id).order_by(Order.CreatedAt.desc()).all()
    )

    return render_template(
        "frontend/pages/order_history.html", orders=orders, title="Lịch sử mua hàng"
    )


@bp.route("/logout")
def logout():
    """Đăng xuất người dùng"""
    session.clear()
    flash("Bạn đã đăng xuất thành công", "success")
    return redirect(url_for("main.home"))


@bp.route("/config")
def show_config():
    app = current_app
    config_info = {
        "environment": app.config.get("ENV") or "development",
        "debug": app.debug,
        "database_uri": app.config.get("SQLALCHEMY_DATABASE_URI"),
        "secret_key": (app.config.get("SECRET_KEY", "Not set") or "")[:10] + "...",
        "upload_folder": app.config.get("UPLOAD_FOLDER"),
        "max_content_length": app.config.get("MAX_CONTENT_LENGTH"),
    }
    return f"<pre>{config_info}</pre>"


@bp.route("/db-info")
def db_info():
    app = current_app
    info = DatabaseConfig.get_database_info(app)
    return f"<pre>{info}</pre>"


@bp.route("/db-check")
def db_check():
    app = current_app
    try:
        with app.app_context():
            db.session.execute(db.text("SELECT 1"))
        return jsonify(status="ok")
    except Exception as e:
        return jsonify(status="error", message=str(e)), 500


@bp.route("/admin")
def dashboard():
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))
    # Render simple dashboard shell; template exists at backend/pages/dashboard.html
    return render_template("backend/pages/dashboard.html")


@bp.route("/about-us")
def about_page():
    return render_template("frontend/pages/ve_chung_toi.html")


@bp.route("/admin/pc-list")
def pc_list():
    """Danh sách sản phẩm PC"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    # Lấy tất cả sản phẩm PC
    pc_products = Product.query.filter_by(IsPC=1).all()

    # Lấy tất cả category có parentID là PC
    pc_parent = Category.query.filter_by(Name="PC").first()
    pc_categories = (
        Category.query.filter_by(ParentID=pc_parent.CategoryID).all()
        if pc_parent
        else []
    )

    return render_template(
        "backend/pages/build_pc/pc_list.html",
        pc_products=pc_products,
        pc_categories=pc_categories,
    )


@bp.route("/admin/create-pc")
def create_pc():
    """Trang tạo sản phẩm PC mới"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    # Lấy tất cả nhóm lựa chọn có sẵn
    available_groups = PcOptionGroup.query.all()
    category_PC = Category.query.filter_by(Name="PC").first()
    pc_categories = Category.query.filter_by(ParentID=category_PC.CategoryID).all()

    return render_template(
        "backend/pages/build_pc/create_pc.html",
        available_groups=available_groups,
        pc_categories=pc_categories,
    )


@bp.route("/admin/create-pc/save", methods=["POST"])
def save_pc_product():
    """Tạo sản phẩm PC mới"""
    if not session.get("is_admin"):
        return jsonify({"success": False, "message": "Không có quyền truy cập"}), 403

    try:
        # Lấy dữ liệu từ FormData request
        pc_name = request.form.get("name")
        pc_description = request.form.get("description", "")
        pc_stock = request.form.get("stock", 1)
        selected_groups_json = request.form.get("selectedGroups", "[]")
        pc_category = request.form.get("pc-category")
        pc_image = request.files.get("pc-image")
        
        # Parse JSON string của selectedGroups
        selected_groups = json.loads(selected_groups_json) if selected_groups_json else []
        
        if not pc_name:
            return jsonify(
                {"success": False, "message": "Tên sản phẩm PC không được để trống"}
            )

        if not pc_category:
            return jsonify(
                {"success": False, "message": "Vui lòng chọn loại PC"}
            )

        if not selected_groups:
            return jsonify(
                {"success": False, "message": "Vui lòng chọn ít nhất một nhóm lựa chọn"}
            )

        # Xử lý upload ảnh
        image_url = None
        if pc_image:
            # Tạo tên file unique
            from werkzeug.utils import secure_filename
            filename = secure_filename(pc_image.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"pc_{timestamp}_{filename}"
            
            # Lưu file vào thư mục static/images/products
            upload_folder = os.path.join("static", "images", "products")
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, unique_filename)
            pc_image.save(file_path)
            
            # Lưu đường dẫn tương đối (không có /static/ ở đầu vì Flask tự động thêm)
            image_url = f"images/products/{unique_filename}"

        # Tạo sản phẩm PC mới
        new_pc = Product(
            Name=pc_name,
            Price=0,  # PC không có giá cơ bản
            Stock=int(pc_stock),
            CategoryID=pc_category,
            BrandID=None,  # PC không cần brand
            Specs=pc_description,
            ImageURL=image_url,
            IsPC=1,  # Đánh dấu là sản phẩm PC
        )

        db.session.add(new_pc)
        db.session.flush()  # Để lấy ProductID

        # Thêm các sản phẩm đã chọn vào các nhóm lựa chọn
        for group_data in selected_groups:
            group_id = group_data["id"]
            products = group_data["products"]

            for product in products:
                # Kiểm tra xem sản phẩm đã tồn tại trong nhóm chưa
                existing_item = PcOptionItem.query.filter_by(
                    OptionGroupID=group_id, ProductID=product["id"]
                ).first()

                if not existing_item:
                    new_item = PcOptionItem(
                        OptionGroupID=group_id,
                        ProductID=product["id"],
                        IsDefault=0,  # Mặc định không phải là lựa chọn mặc định
                    )
                    db.session.add(new_item)

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Sản phẩm PC đã được tạo thành công!",
                "product_id": new_pc.ProductID,
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Lỗi khi tạo sản phẩm PC: {str(e)}"}
        ), 500


@bp.route("/admin/pc/<int:product_id>/manage-groups")
def manage_pc_groups(product_id):
    """Quản lý nhóm lựa chọn cho sản phẩm PC"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    # Lấy sản phẩm PC
    pc_product = Product.query.filter_by(ProductID=product_id, IsPC=1).first_or_404()

    # Lấy tất cả nhóm lựa chọn (độc lập)
    all_groups = PcOptionGroup.query.all()

    # Lấy tất cả sản phẩm linh kiện (không phải PC)
    components = Product.query.filter_by(IsPC=0).all()

    return render_template(
        "backend/pages/build_pc/manage_pc_groups.html",
        pc_product=pc_product,
        all_groups=all_groups,
        components=components,
    )


@bp.route("/admin/pc/<int:product_id>/group/<int:group_id>/add-item", methods=["POST"])
def add_item_to_group(product_id, group_id):
    """Thêm linh kiện vào nhóm lựa chọn"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    component_id = request.form.get("component_id")
    is_default = request.form.get("is_default", 0)

    if not component_id:
        flash("Vui lòng chọn linh kiện", "error")
        return redirect(url_for("main.manage_pc_groups", product_id=product_id))

    try:
        # Kiểm tra xem linh kiện đã tồn tại trong nhóm chưa
        existing_item = PcOptionItem.query.filter_by(
            OptionGroupID=group_id, ProductID=component_id
        ).first()

        if existing_item:
            flash("Linh kiện này đã tồn tại trong nhóm", "error")
            return redirect(url_for("main.manage_pc_groups", product_id=product_id))

        new_item = PcOptionItem(
            OptionGroupID=group_id,
            ProductID=int(component_id),
            IsDefault=int(is_default),
        )
        db.session.add(new_item)
        db.session.commit()
        flash("Thêm linh kiện vào nhóm thành công", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi thêm linh kiện: {str(e)}", "error")

    return redirect(url_for("main.manage_pc_groups", product_id=product_id))


@bp.route(
    "/admin/pc/<int:product_id>/group/<int:group_id>/remove-item/<int:item_id>",
    methods=["POST"],
)
def remove_item_from_group(product_id, group_id, item_id):
    """Xóa linh kiện khỏi nhóm lựa chọn"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    try:
        item = PcOptionItem.query.get(item_id)
        if item and item.OptionGroupID == group_id:
            db.session.delete(item)
            db.session.commit()
            flash("Xóa linh kiện khỏi nhóm thành công", "success")
        else:
            flash("Linh kiện không hợp lệ", "error")
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi xóa linh kiện: {str(e)}", "error")

    return redirect(url_for("main.manage_pc_groups", product_id=product_id))


@bp.route("/admin/pc/<int:product_id>/detail")
def admin_pc_detail(product_id):
    """Trang xem chi tiết sản phẩm PC"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    # Lấy sản phẩm PC
    pc_product = Product.query.filter_by(ProductID=product_id, IsPC=1).first_or_404()

    # Lấy tất cả nhóm lựa chọn có linh kiện (đã được thêm vào PC)
    all_groups = PcOptionGroup.query.all()

    # Lấy tất cả category có parentID là PC
    pc_parent = Category.query.filter_by(Name="PC").first()
    pc_categories = (
        Category.query.filter_by(ParentID=pc_parent.CategoryID).all()
        if pc_parent
        else []
    )

    # Tạo dictionary để lưu thông tin nhóm và sản phẩm
    groups_with_products = []
    for group in all_groups:
        # Lấy tất cả sản phẩm trong nhóm này
        group_items = PcOptionItem.query.filter_by(
            OptionGroupID=group.OptionGroupID
        ).all()

        if group_items:  # Chỉ hiển thị nhóm có sản phẩm (đã được thêm vào PC)
            products_in_group = []
            for item in group_items:
                product = Product.query.get(item.ProductID)
                if product:
                    products_in_group.append(
                        {"product": product, "is_default": item.IsDefault}
                    )

            groups_with_products.append({"group": group, "products": products_in_group})

    # Tags
    product_tags = ProductTag.query.filter_by(ProductID=product_id).all()
    current_tags = [
        Tag.query.get(pt.TagID) for pt in product_tags if Tag.query.get(pt.TagID)
    ]
    all_tags = Tag.query.all()

    return render_template(
        "backend/pages/build_pc/pc_detail.html",
        pc_product=pc_product,
        groups_with_products=groups_with_products,
        pc_categories=pc_categories,
        current_tags=current_tags,
        all_tags=all_tags,
    )


@bp.route("/api/pc/<int:product_id>/available-groups")
def get_available_groups_for_pc(product_id):
    """API endpoint để lấy nhóm lựa chọn chưa được thêm vào PC"""
    try:
        # Lấy sản phẩm PC
        pc_product = Product.query.filter_by(
            ProductID=product_id, IsPC=1
        ).first_or_404()

        # Lấy tất cả nhóm lựa chọn
        all_groups = PcOptionGroup.query.all()

        # Lấy danh sách ID của các nhóm đã có linh kiện (đã được thêm vào PC)
        added_group_ids = [item.OptionGroupID for item in PcOptionItem.query.all()]

        # Lọc ra các nhóm chưa có linh kiện (chưa được thêm vào PC)
        available_groups = []
        for group in all_groups:
            if group.OptionGroupID not in added_group_ids:
                available_groups.append(
                    {
                        "OptionGroupID": group.OptionGroupID,
                        "Name": group.Name,
                        "Description": group.Description,
                        "product_count": 0,  # Nhóm chưa có linh kiện
                    }
                )

        return jsonify({"success": True, "groups": available_groups})

    except Exception as e:
        return jsonify(
            {"success": False, "message": f"Lỗi khi lấy nhóm lựa chọn: {str(e)}"}
        ), 500


@bp.route("/admin/pc/<int:product_id>/add-group", methods=["POST"])
def add_group_to_pc(product_id):
    """Thêm nhóm lựa chọn vào sản phẩm PC"""
    if not session.get("is_admin"):
        return jsonify({"success": False, "message": "Không có quyền truy cập"}), 403

    try:
        group_id = request.form.get("group_id")

        if not group_id:
            return jsonify({"success": False, "message": "Vui lòng chọn nhóm lựa chọn"})

        # Kiểm tra sản phẩm PC tồn tại
        pc_product = Product.query.filter_by(
            ProductID=product_id, IsPC=1
        ).first_or_404()

        # Kiểm tra nhóm lựa chọn tồn tại
        option_group = PcOptionGroup.query.get_or_404(group_id)

        # Kiểm tra xem nhóm đã có linh kiện chưa (đã được thêm vào PC)
        existing_items = PcOptionItem.query.filter_by(OptionGroupID=group_id).all()

        if existing_items:
            return jsonify(
                {
                    "success": False,
                    "message": "Nhóm lựa chọn này đã có linh kiện (đã được thêm vào PC)",
                }
            )

        # Lấy tất cả linh kiện (IsPC=0) để thêm vào nhóm
        all_components = Product.query.filter_by(IsPC=0).all()

        if not all_components:
            return jsonify(
                {"success": False, "message": "Không có linh kiện nào để thêm vào nhóm"}
            )

        # Thêm một linh kiện mặc định vào nhóm (để đánh dấu nhóm đã được thêm vào PC)
        # Chọn linh kiện đầu tiên làm mặc định
        if all_components:
            default_component = all_components[0]
            new_item = PcOptionItem(
                OptionGroupID=group_id,
                ProductID=default_component.ProductID,
                IsDefault=1,
            )
            db.session.add(new_item)

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f'Đã thêm nhóm "{option_group.Name}" vào PC thành công!',
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Lỗi khi thêm nhóm vào PC: {str(e)}"}
        ), 500


@bp.route("/admin/build-pc/<int:group_id>/remove-item", methods=["POST"])
def remove_item_from_group_api(group_id):
    """Xóa linh kiện khỏi nhóm lựa chọn"""
    if not session.get("is_admin"):
        return jsonify({"success": False, "message": "Không có quyền truy cập"}), 403

    try:
        product_id = request.form.get("product_id")

        if not product_id:
            return jsonify(
                {"success": False, "message": "Vui lòng chọn linh kiện cần xóa"}
            )

        # Kiểm tra nhóm lựa chọn tồn tại
        option_group = PcOptionGroup.query.get_or_404(group_id)

        # Kiểm tra linh kiện tồn tại
        product = Product.query.get_or_404(product_id)

        # Tìm và xóa item
        item_to_remove = PcOptionItem.query.filter_by(
            OptionGroupID=group_id, ProductID=product_id
        ).first()

        if not item_to_remove:
            return jsonify(
                {"success": False, "message": "Linh kiện không tồn tại trong nhóm này"}
            )

        # Xóa item
        db.session.delete(item_to_remove)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": f'Đã xóa linh kiện "{product.Name}" khỏi nhóm "{option_group.Name}" thành công!',
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Lỗi khi xóa linh kiện: {str(e)}"}
        ), 500


@bp.route("/admin/pc/<int:product_id>/update", methods=["POST"])
def update_pc_info(product_id):
    """Cập nhật thông tin sản phẩm PC"""
    if not session.get("is_admin"):
        return jsonify({"success": False, "message": "Không có quyền truy cập"}), 403

    try:
        name = request.form.get("name")
        stock = request.form.get("stock")
        description = request.form.get("description")

        if not name or not stock:
            return jsonify(
                {"success": False, "message": "Vui lòng điền đầy đủ thông tin"}
            )

        # Kiểm tra sản phẩm PC tồn tại
        pc_product = Product.query.filter_by(
            ProductID=product_id, IsPC=1
        ).first_or_404()

        # Cập nhật thông tin
        pc_product.Name = name
        pc_product.Stock = int(stock)
        pc_product.Specs = description
        pc_product.UpdatedAt = datetime.utcnow()

        # Xử lý upload ảnh nếu có
        if "edit-pc-image" in request.files:
            image_file = request.files["edit-pc-image"]
            if image_file and image_file.filename:
                # Tạo tên file unique
                filename = (
                    str(uuid.uuid4())
                    + "."
                    + image_file.filename.rsplit(".", 1)[1].lower()
                )

                # Lưu file vào thư mục static/images/products/
                upload_folder = os.path.join(
                    current_app.static_folder, "images", "products"
                )
                os.makedirs(upload_folder, exist_ok=True)

                file_path = os.path.join(upload_folder, filename)
                image_file.save(file_path)

                # Cập nhật đường dẫn ảnh
                pc_product.ImageURL = f"images/products/{filename}"

        db.session.commit()

        return jsonify(
            {"success": True, "message": "Cập nhật thông tin PC thành công!"}
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Lỗi khi cập nhật thông tin: {str(e)}"}
        ), 500


@bp.route("/api/products/group/<int:group_id>")
def get_products_by_group(group_id):
    """API endpoint để lấy sản phẩm theo nhóm lựa chọn"""
    try:
        # Lấy nhóm lựa chọn
        option_group = PcOptionGroup.query.get_or_404(group_id)

        # Lấy danh sách ProductID đã có trong nhóm này
        existing_product_ids = [item.ProductID for item in option_group.items]

        # Map tên nhóm với CategoryID để lọc sản phẩm đúng loại
        # Bạn có thể điều chỉnh mapping này theo database của bạn
        group_name_lower = option_group.Name.lower()
        category_filter = None
        
        # Lấy category dựa trên tên nhóm
        if 'cpu' in group_name_lower or 'processor' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%CPU%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'ram' in group_name_lower or 'memory' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%RAM%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'vga' in group_name_lower or 'gpu' in group_name_lower or 'card' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%VGA%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'ssd' in group_name_lower or 'hdd' in group_name_lower or 'storage' in group_name_lower or 'ổ cứng' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%SSD%')).first()
            if not category:
                category = Category.query.filter(Category.Name.ilike('%HDD%')).first()
            if not category:
                category = Category.query.filter(Category.Name.ilike('%Ổ cứng%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'main' in group_name_lower or 'motherboard' in group_name_lower or 'bo mạch' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%Mainboard%')).first()
            if not category:
                category = Category.query.filter(Category.Name.ilike('%Bo mạch chủ%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'psu' in group_name_lower or 'power' in group_name_lower or 'nguồn' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%Nguồn%')).first()
            if not category:
                category = Category.query.filter(Category.Name.ilike('%PSU%')).first()
            if category:
                category_filter = category.CategoryID
        elif 'case' in group_name_lower or 'vỏ' in group_name_lower:
            category = Category.query.filter(Category.Name.ilike('%Case%')).first()
            if not category:
                category = Category.query.filter(Category.Name.ilike('%Vỏ%')).first()
            if category:
                category_filter = category.CategoryID

        # Query sản phẩm với các điều kiện:
        # 1. IsPC = 0 (chỉ lấy linh kiện, không phải PC hoàn chỉnh)
        # 2. Không nằm trong danh sách đã có trong nhóm
        # 3. Thuộc category tương ứng (nếu xác định được)
        query = Product.query.filter(
            Product.IsPC == 0,
            ~Product.ProductID.in_(existing_product_ids)  # Loại bỏ sản phẩm đã có
        )
        
        if category_filter:
            query = query.filter(Product.CategoryID == category_filter)
        
        products = query.all()

        # Chuyển đổi thành dictionary để trả về JSON
        products_data = []
        for product in products:
            products_data.append(
                {
                    "ProductID": product.ProductID,
                    "Name": product.Name,
                    "Description": product.Specs,  # Sử dụng Specs làm mô tả
                    "Price": product.Price,
                    "CategoryID": product.CategoryID,
                    "CategoryName": product.category.Name if product.category else None,
                    "BrandID": product.BrandID,
                    "BrandName": product.brand.Name if product.brand else None,
                    "ImageURL": product.ImageURL,
                    "Stock": product.Stock,
                }
            )

        return jsonify(
            {
                "success": True,
                "group": {
                    "OptionGroupID": option_group.OptionGroupID,
                    "Name": option_group.Name,
                    "Description": option_group.Description,
                },
                "products": products_data,
                "filtered_by_category": category_filter is not None,
            }
        )

    except Exception as e:
        return jsonify(
            {"success": False, "message": f"Lỗi khi lấy sản phẩm: {str(e)}"}
        ), 500


@bp.route("/admin/pc/<int:product_id>/update-category", methods=["POST"])
def update_pc_category(product_id):
    """Cập nhật loại PC cho sản phẩm"""
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))

    try:
        category_id = request.form.get("category_id")

        # Kiểm tra sản phẩm PC tồn tại
        pc_product = Product.query.filter_by(
            ProductID=product_id, IsPC=1
        ).first_or_404()

        # Cập nhật category
        if category_id:
            pc_product.CategoryID = int(category_id)
        else:
            pc_product.CategoryID = None

        pc_product.UpdatedAt = datetime.utcnow()

        db.session.commit()

        flash("Cập nhật loại PC thành công!", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi cập nhật loại PC: {str(e)}", "error")

    return redirect(url_for("main.admin_pc_detail", product_id=product_id))
