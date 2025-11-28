"""
Configuration package for BanMayTinh_GoiYSanPham
"""
import os
from .setting import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from .database import DatabaseConfig

# Environment configuration
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Get configuration based on environment"""
    config_name = os.environ.get('FLASK_ENV', 'development')
    return config.get(config_name, DevelopmentConfig)