from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import time
import numpy as np
from ultralytics import YOLO


@dataclass
class ROI:
    # ROI rectangle in pixel coords relative to the frame.
    x1: int
    y1: int
    x2: int
    y2: int

    def contains_point(self, x: float, y: float) -> bool:
        return (self.x1 <= x <= self.x2) and (self.y1 <= y <= self.y2)


def _bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    if denom <= 0.0:
        return 0.0
    return inter_area / denom


class ChildLikeDetector:
    """
    YOLOv8 inference wrapper for:
    - child_like class_id = 0
    - adult_like class_id = 1
    We DO NOT estimate biological age. We classify visually.
    """

    def __init__(
        self,
        model_path: str,
        conf_child: float = 0.65,
        device: Optional[str] = None,
        min_child_bbox_ratio: float = 0.18,
        dominance_iou: float = 0.70,
        imgsz: int = 640,
    ):
        self.model_path = model_path
        self.conf_child = float(conf_child)
        self.model = YOLO(model_path)
        self.device = device  # e.g., "cpu" or "0" for GPU
        self.min_child_bbox_ratio = float(min_child_bbox_ratio)
        self.dominance_iou = float(dominance_iou)
        self.imgsz = int(imgsz)

    def infer_frame(self, frame_bgr: np.ndarray, roi: ROI) -> Dict[str, Any]:
        """
        Returns a dict with raw detector decision fields that feed the temporal stabilizer.
        """
        t0 = time.perf_counter()

        # Ultralytics expects BGR numpy image; we keep it as-is.
        results = self.model.predict(
            source=frame_bgr,
            conf=0.25,  # base filter; child threshold is applied below
            iou=0.60,
            agnostic_nms=True,
            imgsz=self.imgsz,
            verbose=False,
            device=self.device,
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        ts_iso = datetime.now(timezone.utc).isoformat()

        # results is a list (1 item for 1 frame)
        r = results[0]
        boxes = r.boxes

        frame_h = frame_bgr.shape[0]
        min_bbox_h = frame_h * self.min_child_bbox_ratio

        detections_out = []
        valid_child_candidates = []

        if boxes is not None and len(boxes) > 0:
            # boxes.xyxy: (N,4), boxes.conf: (N,), boxes.cls: (N,)
            xyxy = boxes.xyxy.cpu().numpy()
            conf = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)

            for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
                detections_out.append(
                    {
                        "bbox": (int(x1), int(y1), int(x2), int(y2)),
                        "conf": float(c),
                        "cls": int(k),
                    }
                )

                # Trigger candidates are child_like only, after confidence + min-size + ROI checks.
                if int(k) != 0 or float(c) < self.conf_child:
                    continue

                bbox_h = float(y2) - float(y1)
                if bbox_h < min_bbox_h:
                    continue

                cx = (float(x1) + float(x2)) / 2.0
                if not roi.contains_point(cx, float(y2)):
                    continue

                valid_child_candidates.append(
                    {
                        "bbox": (float(x1), float(y1), float(x2), float(y2)),
                        "conf": float(c),
                    }
                )

        # Dominance post-filter for near-duplicate trigger candidates.
        kept_candidates = []
        for cand in sorted(valid_child_candidates, key=lambda d: d["conf"], reverse=True):
            if any(_bbox_iou(cand["bbox"], kept["bbox"]) >= self.dominance_iou for kept in kept_candidates):
                continue
            kept_candidates.append(cand)

        child_in_roi_raw = len(kept_candidates) > 0
        confidence_raw = max((d["conf"] for d in kept_candidates), default=0.0)
        roi_status = "CHILD_IN_ROI" if child_in_roi_raw else "CLEAR"

        return {
            "timestamp_iso": ts_iso,
            "latency_ms": latency_ms,
            "confidence_raw": round(confidence_raw, 3),
            "child_in_roi_raw": child_in_roi_raw,
            # Backward-compatible aliases (equal to raw detector decision).
            "confidence": round(confidence_raw, 3),
            "child_in_roi": child_in_roi_raw,
            "roi_status": roi_status,
            "detections": detections_out,
        }
