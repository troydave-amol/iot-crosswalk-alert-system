"""
roi_routes.py — Region of Interest configuration endpoints.

Blueprint: ``roi_bp``
Routes:
    GET  /api/roi  → get current ROI config
    POST /api/roi  → update ROI config (TMC Officer only)
"""

import json
from flask import Blueprint, request, jsonify

from auth.decorators import login_required, role_required
from config import ROI_PATH
from extensions import socketio

roi_bp = Blueprint("roi", __name__)


def _validate_roi_payload(d: dict):
    """Validate polygon or legacy rect ROI payload."""
    if "polygon" in d:
        pts = d.get("polygon", [])
        if not isinstance(pts, list) or len(pts) < 3 or len(pts) > 8:
            return False, "polygon_invalid", d
        try:
            iw = int(d["image_w"])
            ih = int(d["image_h"])
        except (KeyError, TypeError, ValueError):
            return False, "missing_image_size", d
        if iw <= 0 or ih <= 0:
            return False, "bad_image_size", d
        clean_pts = []
        for p in pts:
            try:
                px = max(0, min(int(round(p["x"])), iw))
                py = max(0, min(int(round(p["y"])), ih))
                clean_pts.append({"x": px, "y": py})
            except (KeyError, TypeError, ValueError):
                return False, "bad_point", d
        clean = {"polygon": clean_pts, "image_w": iw, "image_h": ih}
        return True, "", clean
    else:
        required = ["x1", "y1", "x2", "y2", "image_w", "image_h"]
        for k in required:
            if k not in d:
                return False, f"missing:{k}", d
        try:
            iw, ih = int(d["image_w"]), int(d["image_h"])
        except Exception:
            return False, "type_error", d
        if iw <= 0 or ih <= 0:
            return False, "bad_image_size", d
        x1 = max(0, min(int(round(d["x1"])), iw - 1))
        y1 = max(0, min(int(round(d["y1"])), ih - 1))
        x2 = max(x1 + 1, min(int(round(d["x2"])), iw))
        y2 = max(y1 + 1, min(int(round(d["y2"])), ih))
        clean = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "image_w": iw, "image_h": ih}
        return True, "", clean


@roi_bp.get("/api/roi")
@login_required
def api_get_roi():
    if not ROI_PATH.exists():
        return jsonify({"ok": False, "error": "roi_not_set"}), 404
    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))
    return jsonify({"ok": True, "roi": data})


@roi_bp.post("/api/roi")
@role_required("tmc_officer")
def api_set_roi():
    d = request.get_json(silent=True) or {}
    ok, err, clean = _validate_roi_payload(d)
    if not ok:
        print(f"[ROI] Validation failed: {err} | payload={d}")
        return jsonify({"ok": False, "error": err}), 400

    ROI_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    print(f"[ROI] Saved: {clean}")
    socketio.emit("roi_updated", {"roi": clean})
    return jsonify({"ok": True})
