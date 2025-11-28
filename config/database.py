"""
Database configuration and utilities
"""
import os
import sqlite3
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from .setting import Config

# Initialize database
db = SQLAlchemy()
migrate = Migrate()

class DatabaseConfig:
    """Database configuration class"""
    
    @staticmethod
    def init_app(app):
        """Initialize database with Flask app"""
        # Configure SQLAlchemy
        db.init_app(app)
        migrate.init_app(app, db)
        # Ensure models are imported so SQLAlchemy can discover them
        try:
            import models  # noqa: F401
        except Exception as import_err:
            app.logger.warning(f"Models import warning: {import_err}")
        
        # Create instance directory if it doesn't exist
        instance_path = os.path.join(app.root_path, 'instance')
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
        
        # Create database file if it doesn't exist
        DatabaseConfig.create_database_if_not_exists(app)
    
    @staticmethod
    def create_database_if_not_exists(app):
        """Create SQLite database file if it doesn't exist"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            # Extract database file path
            db_path = database_uri.replace('sqlite:///', '')
            
            # Create directory if it doesn't exist
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
            
            # Create database file if it doesn't exist
            if not os.path.exists(db_path):
                try:
                    # Create empty SQLite database
                    conn = sqlite3.connect(db_path)
                    conn.close()
                    app.logger.info(f"Created SQLite database: {db_path}")
                except Exception as e:
                    app.logger.error(f"Error creating database: {e}")
            else:
                app.logger.info(f"SQLite database already exists: {db_path}")
    
    @staticmethod
    def get_database_info(app):
        """Get database information"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
            return {
                'type': 'SQLite',
                'path': db_path,
                'exists': os.path.exists(db_path),
                'size': os.path.getsize(db_path) if os.path.exists(db_path) else 0
            }
        else:
            return {
                'type': 'Other',
                'uri': database_uri,
                'exists': True,
                'size': 0
            }
    
    @staticmethod
    def backup_database(app, backup_path=None):
        """Backup SQLite database"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
            
            if not backup_path:
                backup_path = f"{db_path}.backup"
            
            try:
                import shutil
                shutil.copy2(db_path, backup_path)
                app.logger.info(f"Database backed up to: {backup_path}")
                return backup_path
            except Exception as e:
                app.logger.error(f"Error backing up database: {e}")
                return None
        else:
            app.logger.warning("Backup only supported for SQLite databases")
            return None
    
    @staticmethod
    def restore_database(app, backup_path):
        """Restore SQLite database from backup"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
            
            try:
                import shutil
                shutil.copy2(backup_path, db_path)
                app.logger.info(f"Database restored from: {backup_path}")
                return True
            except Exception as e:
                app.logger.error(f"Error restoring database: {e}")
                return False
        else:
            app.logger.warning("Restore only supported for SQLite databases")
            return False
    
    @staticmethod
    def get_table_info(app):
        """Get information about database tables"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Get table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                
                table_info = []
                for table in tables:
                    table_name = table[0]
                    
                    # Get table schema
                    cursor.execute(f"PRAGMA table_info({table_name});")
                    columns = cursor.fetchall()
                    
                    # Get row count
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
                    row_count = cursor.fetchone()[0]
                    
                    table_info.append({
                        'name': table_name,
                        'columns': len(columns),
                        'rows': row_count,
                        'schema': columns
                    })
                
                conn.close()
                return table_info
            except Exception as e:
                app.logger.error(f"Error getting table info: {e}")
                return []
        else:
            app.logger.warning("Table info only supported for SQLite databases")
            return []
    
    @staticmethod
    def execute_raw_query(app, query):
        """Execute raw SQL query (for SQLite)"""
        database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        
        if database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                cursor.execute(query)
                
                if query.strip().upper().startswith('SELECT'):
                    results = cursor.fetchall()
                    conn.close()
                    return results
                else:
                    conn.commit()
                    conn.close()
                    return True
            except Exception as e:
                app.logger.error(f"Error executing query: {e}")
                return None
        else:
            app.logger.warning("Raw queries only supported for SQLite databases")
            return None
