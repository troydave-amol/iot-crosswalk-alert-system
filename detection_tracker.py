"""
detection_tracker.py — Lightweight IoU-based bounding box tracker for anti-flicker.

Smooths YOLO detections across consecutive frames so bounding boxes don't
strobe on/off when the detector briefly loses a target due to motion blur,
pixelation, shadows, or pose changes.

Architecture:
    YOLO raw detections ──► DetectionTracker.update() ──► stabilized detections
                                                           ├── overlay drawing
                                                           └── ROI child logic

Fail-safe: If any internal error occurs, the tracker transparently returns
the raw detections unchanged so the pipeline never crashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Track:
    """A single tracked object persisting across frames."""
    track_id: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2) — smoothed
    conf: float
    cls: int
    hits: int = 1          # total frames this track has been matched
    misses: int = 0        # consecutive frames without a matching detection
    _bbox_smooth: Tuple[float, float, float, float] = field(init=False, repr=False)

    def __post_init__(self):
        self._bbox_smooth = tuple(float(v) for v in self.bbox)


def _iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    """Compute Intersection-over-Union between two (x1,y1,x2,y2) boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class DetectionTracker:
    """
    IoU-based greedy tracker with exponential moving average (EMA) box smoothing.

    Parameters
    ----------
    iou_threshold : float
        Minimum IoU to consider a detection and an existing track the same object.
        Lower = more tolerant of movement between frames. Default 0.25.
    max_misses : int
        How many consecutive frames a track survives without a matching detection.
        At 8 FPS, 5 misses ≈ 0.6 seconds of persistence. Default 5.
    smooth_alpha : float
        EMA weight for box position smoothing.
        1.0 = no smoothing (snap to new position immediately).
        0.3 = very smooth (slow to react). Default 0.6.
    """

    def __init__(
        self,
        iou_threshold: float = 0.25,
        max_misses: int = 5,
        smooth_alpha: float = 0.6,
    ):
        self.iou_threshold = float(iou_threshold)
        self.max_misses = int(max_misses)
        self.smooth_alpha = max(0.1, min(1.0, float(smooth_alpha)))
        self._tracks: Dict[int, Track] = {}
        self._next_id: int = 1

    def update(self, detections: List[dict]) -> List[dict]:
        """
        Match incoming YOLO detections to existing tracks and return
        stabilized detections (including 'ghost' boxes for recent misses).

        Parameters
        ----------
        detections : list of dict
            Each dict has keys: bbox (x1,y1,x2,y2), conf (float), cls (int).

        Returns
        -------
        list of dict
            Stabilized detections in the same format, with an extra 'track_id' key.
        """
        try:
            return self._update_internal(detections)
        except Exception:
            # Fail-safe: return raw detections unchanged if anything breaks
            return detections

    def _update_internal(self, detections: List[dict]) -> List[dict]:
        # --- Step 1: Build cost matrix (IoU) for greedy matching ---
        matched_det_indices: set = set()
        matched_track_ids: set = set()

        # Sort detections by confidence (highest first) so the best
        # detections get first pick of tracks.
        det_order = sorted(range(len(detections)), key=lambda i: detections[i]["conf"], reverse=True)

        for det_idx in det_order:
            det = detections[det_idx]
            det_bbox = det["bbox"]
            det_cls = det["cls"]

            best_iou = 0.0
            best_track_id: Optional[int] = None

            for tid, track in self._tracks.items():
                if tid in matched_track_ids:
                    continue
                # Only match same class
                if track.cls != det_cls:
                    continue
                iou = _iou(det_bbox, track.bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = tid

            if best_track_id is not None and best_iou >= self.iou_threshold:
                # --- Matched: update track ---
                track = self._tracks[best_track_id]
                track.hits += 1
                track.misses = 0
                track.conf = det["conf"]
                track.cls = det["cls"]

                # EMA smooth the bounding box
                alpha = self.smooth_alpha
                old = track._bbox_smooth
                new = tuple(float(v) for v in det_bbox)
                track._bbox_smooth = tuple(
                    alpha * n + (1.0 - alpha) * o for n, o in zip(new, old)
                )
                track.bbox = tuple(int(round(v)) for v in track._bbox_smooth)

                matched_det_indices.add(det_idx)
                matched_track_ids.add(best_track_id)

        # --- Step 2: Create new tracks for unmatched detections ---
        for det_idx in range(len(detections)):
            if det_idx in matched_det_indices:
                continue
            det = detections[det_idx]
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = Track(
                track_id=tid,
                bbox=det["bbox"],
                conf=det["conf"],
                cls=det["cls"],
            )
            matched_track_ids.add(tid)

        # --- Step 3: Increment misses on unmatched tracks ---
        for tid in list(self._tracks.keys()):
            if tid not in matched_track_ids:
                self._tracks[tid].misses += 1

        # --- Step 4: Expire tracks that exceeded max_misses ---
        expired = [tid for tid, t in self._tracks.items() if t.misses > self.max_misses]
        for tid in expired:
            del self._tracks[tid]

        # --- Step 5: Build output (all active tracks, including ghosts) ---
        output: List[dict] = []
        for track in self._tracks.values():
            output.append({
                "bbox": track.bbox,
                "conf": track.conf,
                "cls": track.cls,
                "track_id": track.track_id,
            })

        return output
