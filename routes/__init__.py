"""routes — Flask Blueprints for the crosswalk alert system."""

from routes.auth_routes import auth_bp
from routes.roi_routes import roi_bp
from routes.events_routes import events_bp
from routes.camera_routes import camera_bp
from routes.mode_routes import mode_bp


def register_blueprints(app):
    """Register all route blueprints with the Flask application."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(roi_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(mode_bp)
    