"""
overlay_renderer.py — Video frame overlay drawing utilities.

Provides ``draw_overlay()`` which renders ROI polygons, bounding boxes,
and status labels onto video frames for MJPEG streaming.
"""

from typing import Optional

import cv2

from cv_inference import ROI


def draw_overlay(frame, roi: ROI, detections, child_in_roi: bool, status_note: Optional[str] = None):
    """Draw ROI polygon, detection bounding boxes, and status text onto a frame."""
    if roi:
        roi_overlay = frame.copy()
        if child_in_roi:
            fill_color = (0, 0, 200)   # Red tint = WARNING
            border_color = (0, 0, 255)
        else:
            fill_color = (0, 180, 0)   # Green tint = CLEAR
            border_color = (0, 255, 0)
        # Draw filled polygon overlay
        pts = roi.polygon.reshape((-1, 1, 2))
        cv2.fillPoly(roi_overlay, [roi.polygon], fill_color)
        cv2.addWeighted(roi_overlay, 0.08, frame, 0.92, 0, frame)
        cv2.polylines(frame, [pts], isClosed=True, color=border_color, thickness=2)

        roi_label = "ROI: CHILD DETECTED" if child_in_roi else "ROI: CLEAR"
        (tw, th), _ = cv2.getTextSize(roi_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        lx = roi.x1
        ly = max(th + 10, roi.y1 - 10)
        cv2.rectangle(frame, (lx, ly - th - 6), (lx + tw + 8, ly + 4), (0, 0, 0), -1)
        cv2.putText(frame, roi_label, (lx + 4, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.8, border_color, 2, cv2.LINE_AA)

    if status_note:
        (tw, th), _ = cv2.getTextSize(status_note, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        pad = 10
        top = 16
        cv2.rectangle(frame, (pad, top), (pad + tw + 16, top + th + 16), (0, 120, 255), -1)
        cv2.putText(
            frame,
            status_note,
            (pad + 8, top + th + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        conf = d["conf"]
        cls = d["cls"]
        if cls == 1:
            color = (0, 255, 255)  # Cyan
            label = f"child {conf:.2f}"
            thickness = 1
        else:
            color = (255, 180, 50)  # Orange
            label = f"adult {conf:.2f}"
            thickness = 1
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), (0, 0, 0), -1)
        cv2.putText(frame, label, (x1 + 3, max(th + 3, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    return frame
