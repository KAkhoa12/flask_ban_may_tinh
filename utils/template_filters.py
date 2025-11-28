import json

def from_json(value):
    """Convert JSON string to Python object"""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None

def register_filters(app):
    """Register custom template filters"""
    app.jinja_env.filters['from_json'] = from_json