"""
auth_routes.py — Landing page, dashboard routing, login/logout, password management.

Blueprint: ``auth_bp``
Routes:
    GET  /                           → landing page
    GET  /dashboard                  → role-based redirect
    GET  /dashboard/tmc              → TMC Officer dashboard
    GET  /dashboard/it               → IT Specialist dashboard
    POST /api/login                  → authenticate credentials
    GET  /api/logout                 → clear session & redirect
    POST /api/user/change-password   → update own password
"""

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for

from auth.decorators import login_required, role_required
from config import MODEL_PATH, CHILD_CONF, YOLO_IMGSZ
from db import authenticate_user, update_user_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def landing():
    """Landing / Welcome page with login form."""
    if session.get("logged_in"):
        return redirect(url_for("auth.dashboard"))
    return render_template("landing.html")


@auth_bp.route("/dashboard")
@login_required
def dashboard():
    """Dynamic router — redirects to the role-appropriate dashboard."""
    role = session.get("role")
    if role == "it_specialist":
        return redirect(url_for("auth.dashboard_it"))
    return redirect(url_for("auth.dashboard_tmc"))


@auth_bp.route("/dashboard/tmc")
@role_required("tmc_officer")
def dashboard_tmc():
    """TMC Officer dashboard — live view, ROI, logs, analytics, reports."""
    return render_template("tmc_dashboard.html",
                           username=session.get("username"),
                           role=session.get("role"),
                           full_name=session.get("full_name", "TMC Officer"))


@auth_bp.route("/dashboard/it")
@role_required("it_specialist")
def dashboard_it():
    """IT Specialist dashboard — system status, video sim, data export, model accuracy."""
    return render_template("it_dashboard.html",
                           username=session.get("username"),
                           role=session.get("role"),
                           full_name=session.get("full_name", "IT Specialist"),
                           model_name=MODEL_PATH.name,
                           model_path=str(MODEL_PATH),
                           child_conf=CHILD_CONF,
                           yolo_imgsz=YOLO_IMGSZ)


@auth_bp.route("/api/login", methods=["POST"])
def api_login():
    """Authenticate credentials against MySQL users table."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    user = authenticate_user(username, password)
    if user:
        session["logged_in"] = True
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        session["user_id"] = user["id"]
        session.permanent = True
        return jsonify({"ok": True, "role": user["role"], "redirect": url_for("auth.dashboard")})

    return jsonify({"ok": False, "error": "Invalid username or password."}), 401


@auth_bp.route("/api/logout")
def api_logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    return redirect(url_for("auth.landing"))


@auth_bp.route("/api/user/change-password", methods=["POST"])
@login_required
def api_change_password():
    """Allow authenticated users to update their own password."""
    data = request.get_json(silent=True) or {}
    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()

    if not current_password or not new_password:
        return jsonify({"ok": False, "error": "Both current and new password are required."}), 400

    if len(new_password) < 6:
        return jsonify({"ok": False, "error": "New password must be at least 6 characters."}), 400

    # Verify current password matches
    username = session.get("username")
    user = authenticate_user(username, current_password)
    if not user:
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 401

    # Update to new password
    if update_user_password(username, new_password):
        return jsonify({"ok": True, "message": "Password updated successfully."})
    return jsonify({"ok": False, "error": "Failed to update password. Please try again."}), 500
