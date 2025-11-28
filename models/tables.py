"""
SQLAlchemy ORM models mapping to schema in config/sql.sql
"""
from datetime import datetime
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from config.database import db


class User(db.Model):
    __tablename__ = 'user'

    UserID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)
    Email = db.Column(db.String, unique=True, nullable=False)
    PasswordHash = db.Column(db.String, nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    Role = db.Column(db.String, default='user')
    IsDelete = db.Column(db.Boolean, default=False)
    carts = relationship('Cart', back_populates='user', cascade='all, delete-orphan')
    orders = relationship('Order', back_populates='user', cascade='all, delete-orphan')


class Brand(db.Model):
    __tablename__ = 'brand'

    BrandID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)

    products = relationship('Product', back_populates='brand')


class Category(db.Model):
    __tablename__ = 'category'

    CategoryID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)
    ParentID = db.Column(db.Integer, ForeignKey('category.CategoryID'), nullable=True)

    parent = relationship('Category', remote_side=[CategoryID], backref='children')
    products = relationship('Product', back_populates='category')


class Product(db.Model):
    __tablename__ = 'product'

    ProductID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)
    CategoryID = db.Column(db.Integer, ForeignKey('category.CategoryID'), nullable=False)
    BrandID = db.Column(db.Integer, ForeignKey('brand.BrandID'), nullable=True)
    Price = db.Column(db.Float, nullable=False)
    IsPC = db.Column(db.Integer, default=0)
    Specs = db.Column(db.Text)
    ImageURL = db.Column(db.String)
    Stock = db.Column(db.Integer, default=0)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    category = relationship('Category', back_populates='products')
    brand = relationship('Brand', back_populates='products')
    cart_details = relationship('CartDetail', back_populates='product')
    order_details = relationship('OrderDetail', back_populates='product')
    tags = relationship('ProductTag', back_populates='product', cascade='all, delete-orphan')


class Cart(db.Model):
    __tablename__ = 'cart'

    CartID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    UserID = db.Column(db.Integer, ForeignKey('user.UserID'), nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='carts')
    details = relationship('CartDetail', back_populates='cart', cascade='all, delete-orphan')


class CartDetail(db.Model):
    __tablename__ = 'cartdetail'

    CartDetailID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    CartID = db.Column(db.Integer, ForeignKey('cart.CartID'), nullable=False)
    ProductID = db.Column(db.Integer, ForeignKey('product.ProductID'), nullable=False)
    Quantity = db.Column(db.Integer, nullable=False, default=1)
    Price = db.Column(db.Float, nullable=False)
    ConfigData = db.Column(db.Text, nullable=True)

    cart = relationship('Cart', back_populates='details')
    product = relationship('Product', back_populates='cart_details')


class Order(db.Model):
    __tablename__ = 'order'

    OrderID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    UserID = db.Column(db.Integer, ForeignKey('user.UserID'), nullable=False)
    TotalPrice = db.Column(db.Float, nullable=False)
    Status = db.Column(db.String, default='pending')
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    user = relationship('User', back_populates='orders')
    details = relationship('OrderDetail', back_populates='order', cascade='all, delete-orphan')


class OrderDetail(db.Model):
    __tablename__ = 'orderdetail'

    OrderDetailID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    OrderID = db.Column(db.Integer, ForeignKey('order.OrderID'), nullable=False)
    ProductID = db.Column(db.Integer, ForeignKey('product.ProductID'), nullable=False)
    Quantity = db.Column(db.Integer, nullable=False, default=1)
    Price = db.Column(db.Float, nullable=False)
    ConfigData = db.Column(db.Text, nullable=True)

    order = relationship('Order', back_populates='details')
    product = relationship('Product', back_populates='order_details')


class PcOptionGroup(db.Model):
    __tablename__ = 'pc_option_group'

    OptionGroupID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)
    Description = db.Column(db.String, nullable=True)
    items = relationship('PcOptionItem', back_populates='group', cascade='all, delete-orphan')


class PcOptionItem(db.Model):
    __tablename__ = 'pc_option_item'

    OptionItemID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    OptionGroupID = db.Column(db.Integer, ForeignKey('pc_option_group.OptionGroupID'), nullable=False)
    ProductID = db.Column(db.Integer, ForeignKey('product.ProductID'), nullable=False)
    IsDefault = db.Column(db.Integer, default=0)

    group = relationship('PcOptionGroup', back_populates='items')
    product = relationship('Product')


class Tag(db.Model):
    __tablename__ = 'tag'

    TagID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Name = db.Column(db.String, nullable=False)

    products = relationship('ProductTag', back_populates='tag', cascade='all, delete-orphan')


class ProductTag(db.Model):
    __tablename__ = 'product_tag'

    ProductTagID = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ProductID = db.Column(db.Integer, ForeignKey('product.ProductID'), nullable=False)
    TagID = db.Column(db.Integer, ForeignKey('tag.TagID'), nullable=False)

    product = relationship('Product', back_populates='tags')
    tag = relationship('Tag', back_populates='products')

    __table_args__ = (
        UniqueConstraint('ProductID', 'TagID', name='uq_product_tag'),
    )



