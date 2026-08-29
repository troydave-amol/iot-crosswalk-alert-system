"""
decorators.py — Authentication and RBAC decorators.

Provides ``@login_required`` and ``@role_required`` for protecting Flask
routes.  These decorators rely on ``flask.session`` — they import nothing
from ``app.py`` and are therefore safe from circular imports.
"""

import functools

from flask import session, request, jsonify, redirect, url_for, render_template


def login_required(f):
    """Decorator to protect routes that require authentication (any role)."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """Decorator to enforce role-based access control.
    Usage: @role_required('tmc_officer') or @role_required('tmc_officer', 'it_specialist')
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "unauthorized"}), 401
                return redirect(url_for("landing"))
            user_role = session.get("role")
            if allowed_roles and user_role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify({
                        "ok": False,
                        "error": "forbidden",
                        "message": f"Requires one of roles: {', '.join(allowed_roles)}"
                    }), 403
                return render_template("403.html", user_role=user_role), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
