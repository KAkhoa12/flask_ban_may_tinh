"""
Routes package exposing blueprints
"""

from .admins import bp as admins_bp
from .auth import bp as auth_bp
from .brands import bp as brands_bp
from .build_pc import bp as build_pc_bp
from .categories import bp as categories_bp
from .chatbot import bp as chatbot_bp
from .main import bp as main_bp
from .orders import bp as orders_bp
from .products import bp as products_bp
from .tags import bp as tags_bp
from .users import bp as users_bp

__all__ = [
    "main_bp",
    "auth_bp",
    "categories_bp",
    "brands_bp",
    "products_bp",
    "build_pc_bp",
    "tags_bp",
    "users_bp",
    "orders_bp",
    "admins_bp",
    "chatbot_bp",
]
