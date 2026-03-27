import os

from flask import Flask

from config import get_config
from config.database import DatabaseConfig, db
from routes import (
    admins_bp,
    auth_bp,
    brands_bp,
    build_pc_bp,
    categories_bp,
    chatbot_bp,
    main_bp,
    orders_bp,
    products_bp,
    tags_bp,
    users_bp,
)
from utils.template_filters import register_filters


def create_app():
    """Application factory pattern"""
    app = Flask(__name__)

    # Load configuration
    config_class = get_config()
    app.config.from_object(config_class)

    # Initialize database
    DatabaseConfig.init_app(app)

    # Initialize configuration
    config_class.init_app(app)

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(brands_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(build_pc_bp)
    app.register_blueprint(tags_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(admins_bp)
    app.register_blueprint(chatbot_bp)

    # Register custom template filters
    register_filters(app)

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
