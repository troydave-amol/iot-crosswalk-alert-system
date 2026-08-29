"""
roi_manager.py — ROI configuration loading, scaling, and validation.

Provides ``load_roi_for_frame()`` which reads ``roi_config.json`` and
scales the ROI polygon/rectangle to match the current video frame size.
"""

import json

from config import ROI_PATH
from cv_inference import ROI


def load_roi_for_frame(frame_w: int, frame_h: int) -> ROI:
    """
    Loads ROI saved from Settings ROI tool and scales to current frame size.
    Supports both polygon format (4 corner points) and legacy rect format.
    """
    if not ROI_PATH.exists():
        return ROI.from_rect(0, 0, frame_w - 1, frame_h - 1, frame_w, frame_h)

    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))
    base_w = int(data.get("image_w", frame_w))
    base_h = int(data.get("image_h", frame_h))
    sx = frame_w / base_w
    sy = frame_h / base_h

    if "polygon" in data:
        pts = data["polygon"]
        import numpy as _np
        polygon = _np.array([[int(p["x"] * sx), int(p["y"] * sy)] for p in pts], dtype=_np.int32)
        return ROI(polygon, frame_w, frame_h)
    else:
        x1 = int(int(data.get("x1", 0)) * sx)
        y1 = int(int(data.get("y1", 0)) * sy)
        x2 = int(int(data.get("x2", 0)) * sx)
        y2 = int(int(data.get("y2", 0)) * sy)
        return ROI.from_rect(x1, y1, x2, y2, frame_w, frame_h)
