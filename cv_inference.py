from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any, List

import time
import numpy as np
from ultralytics import YOLO


@dataclass
class ROI:
    # ROI rectangle in pixel coords relative to the frame
    x1: int
    y1: int
    x2: int
    y2: int

    def contains_point(self, x: float, y: float) -> bool:
        return (self.x1 <= x <= self.x2) and (self.y1 <= y <= self.y2)


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
    ):
        self.model_path = model_path
        self.conf_child = conf_child
        self.model = YOLO(model_path)
        self.device = device  # e.g., "cpu" or "0" for GPU

    def infer_frame(self, frame_bgr: np.ndarray, roi: ROI) -> Dict[str, Any]:
        """
        Returns a stable dict you can plug into status_update later.
        """
        t0 = time.perf_counter()

        # Ultralytics expects BGR numpy image; we keep it as-is
        results = self.model.predict(
            source=frame_bgr,
            conf=0.25,          # base filter; we enforce child threshold separately
            iou=0.5,
            verbose=False,
            device=self.device
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        ts_iso = datetime.now(timezone.utc).isoformat()

        child_in_roi = False
        best_child_conf = 0.0

        # results is a list (1 item for 1 frame)
        r = results[0]
        boxes = r.boxes

        if boxes is not None and len(boxes) > 0:
            # boxes.xyxy: (N,4), boxes.conf: (N,), boxes.cls: (N,)
            xyxy = boxes.xyxy.cpu().numpy()
            conf = boxes.conf.cpu().numpy()
            cls  = boxes.cls.cpu().numpy().astype(int)

            for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls):
                # Only care about child_like class_id = 0
                if k != 0:
                    continue
                if float(c) < self.conf_child:
                    continue

                cx = (float(x1) + float(x2)) / 2.0
                cy = (float(y1) + float(y2)) / 2.0

                if roi.contains_point(cx, cy):
                    child_in_roi = True
                    if float(c) > best_child_conf:
                        best_child_conf = float(c)

        roi_status = "CHILD_IN_ROI" if child_in_roi else "CLEAR"

        return {
            "timestamp_iso": ts_iso,
            "latency_ms": latency_ms,
            "confidence": round(best_child_conf, 3),
            "child_in_roi": child_in_roi,
            "roi_status": roi_status,
        }
