"""
detection_tracker.py — Kalman Filter + ByteTrack Cascaded Association + Probability EMA Tracker.

Stabilizes YOLO detections across consecutive frames to prevent:
1. Bounding box strobing/flickering from motion blur, pixelation, or frame drops.
2. Track ID fragmentation during rapid pedestrian or running child movement.
3. Class label flapping between child and adult using continuous Probability EMA
   consensus with dual-threshold Schmitt trigger hysteresis.
4. Track dropouts during temporary occlusion via ByteTrack two-stage cascaded matching.

Architecture:
    YOLO raw detections ──► DetectionTracker.update() ──► stabilized detections
                                                           ├── overlay drawing
                                                           └── ROI child logic

Pipeline:
    1. Kalman 2D State Prediction (constant-velocity motion model)
    2. Stage 1 Association: Match active tracks with High-Confidence detections
    3. Stage 2 Association: Match remaining tracks with Low-Confidence detections (occlusion recovery)
    4. New Track Initialization: Only high-confidence unmatched detections spawn tracks
    5. Probability EMA Consensus: Recursive posterior belief with asymmetric Schmitt trigger
    6. Establishment-Gated Ghost Persistence: Kalman-propagated boxes for confirmed targets

Fail-safe: If any internal error occurs, the tracker transparently returns
the raw detections unchanged so the pipeline never crashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------------
# Minimum establishment threshold: tracks with fewer cumulative hits than
# this value are expired immediately (1 miss = death) to prevent single-frame
# hallucinations from lingering as ghost boxes.
# ---------------------------------------------------------------------------
ESTABLISHMENT_MIN_HITS = 5

# Default backward-compatible hysteresis threshold
DEFAULT_CLASS_SWITCH_FRAMES = 15


def _bbox_to_z(bbox: Tuple[int, int, int, int]) -> np.ndarray:
    """Convert (x1, y1, x2, y2) to measurement vector [xc, yc, a, h]^T."""
    x1, y1, x2, y2 = bbox
    w = max(1.0, float(x2 - x1))
    h = max(1.0, float(y2 - y1))
    xc = float(x1) + w / 2.0
    yc = float(y1) + h / 2.0
    a = w / h
    return np.array([[xc], [yc], [a], [h]], dtype=np.float64)


def _z_to_bbox(x: np.ndarray) -> Tuple[int, int, int, int]:
    """Convert state vector x back to (x1, y1, x2, y2) bounding box."""
    xc = float(x[0, 0])
    yc = float(x[1, 0])
    a = max(0.01, float(x[2, 0]))
    h = max(1.0, float(x[3, 0]))
    w = a * h
    x1 = int(round(xc - w / 2.0))
    y1 = int(round(yc - h / 2.0))
    x2 = int(round(xc + w / 2.0))
    y2 = int(round(yc + h / 2.0))
    return (x1, y1, x2, y2)


class KalmanBoxTracker:
    """
    2D Linear Kalman Filter tracking bounding box state:
    x = [x_c, y_c, a, h, v_x, v_y, v_a, v_h]^T
    Constant velocity motion model for pedestrian tracking.
    """

    def __init__(self, bbox: Tuple[int, int, int, int]):
        # State transition matrix F (8x8)
        self.F = np.eye(8, dtype=np.float64)
        for i in range(4):
            self.F[i, i + 4] = 1.0  # position += velocity * dt (dt=1)

        # Measurement matrix H (4x8)
        self.H = np.zeros((4, 8), dtype=np.float64)
        for i in range(4):
            self.H[i, i] = 1.0

        # Measurement noise covariance R (4x4)
        self.R = np.diag([1.0, 1.0, 10.0, 1.0]).astype(np.float64)

        # Process noise covariance Q (8x8)
        self.Q = np.diag([
            1.0, 1.0, 1.0, 1.0,          # position variance
            0.01, 0.01, 0.0001, 0.01      # velocity variance
        ]).astype(np.float64)

        # State covariance matrix P (8x8)
        self.P = np.diag([
            10.0, 10.0, 10.0, 10.0,
            1000.0, 1000.0, 1000.0, 1000.0
        ]).astype(np.float64)

        # State vector x (8x1)
        self.x = np.zeros((8, 1), dtype=np.float64)
        self.x[:4] = _bbox_to_z(bbox)

        self.last_predicted_bbox: Tuple[int, int, int, int] = bbox

    def predict(self) -> Tuple[int, int, int, int]:
        """Advance state forward by one step and return predicted bounding box."""
        # x = F * x
        self.x = np.dot(self.F, self.x)
        # Constrain aspect ratio and height to plausible bounds
        self.x[2, 0] = max(0.05, min(5.0, self.x[2, 0]))
        self.x[3, 0] = max(5.0, self.x[3, 0])
        # P = F * P * F^T + Q
        self.P = np.dot(np.dot(self.F, self.P), self.F.T) + self.Q

        self.last_predicted_bbox = _z_to_bbox(self.x)
        return self.last_predicted_bbox

    def update(self, bbox: Tuple[int, int, int, int]):
        """Update Kalman state with observed detection bounding box."""
        z = _bbox_to_z(bbox)
        # Innovation y = z - H * x
        y = z - np.dot(self.H, self.x)
        # Innovation covariance S = H * P * H^T + R
        S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R
        # Kalman gain K = P * H^T * S^-1
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))
        # x = x + K * y
        self.x = self.x + np.dot(K, y)
        # P = (I - K * H) * P
        I = np.eye(8, dtype=np.float64)
        self.P = np.dot(I - np.dot(K, self.H), self.P)
        self.last_predicted_bbox = _z_to_bbox(self.x)


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


def _match_boxes(
    tracks: List["Track"],
    detections: List[dict],
    iou_thresh: float,
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Associate tracks and detections using Hungarian assignment on IoU distance.
    Returns:
        matched_pairs: list of (track_idx, det_idx)
        unmatched_tracks: list of track_idx
        unmatched_dets: list of det_idx
    """
    if len(tracks) == 0:
        return [], [], list(range(len(detections)))
    if len(detections) == 0:
        return [], list(range(len(tracks))), []

    iou_matrix = np.zeros((len(tracks), len(detections)), dtype=np.float32)
    for t_idx, track in enumerate(tracks):
        pred_box = track.kalman.last_predicted_bbox
        for d_idx, det in enumerate(detections):
            iou_matrix[t_idx, d_idx] = _iou(pred_box, det["bbox"])

    cost_matrix = 1.0 - iou_matrix
    row_ind, col_ind = linear_sum_assignment(cost_matrix)

    matched_pairs = []
    matched_track_set = set()
    matched_det_set = set()

    for r, c in zip(row_ind, col_ind):
        if iou_matrix[r, c] >= iou_thresh:
            matched_pairs.append((r, c))
            matched_track_set.add(r)
            matched_det_set.add(c)

    unmatched_tracks = [i for i in range(len(tracks)) if i not in matched_track_set]
    unmatched_dets = [j for j in range(len(detections)) if j not in matched_det_set]

    return matched_pairs, unmatched_tracks, unmatched_dets


@dataclass
class Track:
    """A single tracked object persisting across frames."""
    track_id: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2) — smoothed
    conf: float                       # EMA-smoothed confidence
    cls: int                          # stable class (hysteresis-gated)
    hits: int = 1          # total frames this track has been matched
    misses: int = 0        # consecutive frames without a matching detection

    # Probability EMA consensus state
    prob_child: float = 0.5
    prob_beta: float = 0.80
    child_enter_thresh: float = 0.60
    child_exit_thresh: float = 0.35

    # Internal smoothing and Kalman state
    kalman: KalmanBoxTracker = field(default=None, repr=False)
    _bbox_smooth: Tuple[float, float, float, float] = field(init=False, repr=False)
    _conf_smooth: float = field(init=False, repr=False)
    _opposing_streak: int = field(default=0, init=False, repr=False)

    def __post_init__(self):
        self._bbox_smooth = tuple(float(v) for v in self.bbox)
        self._conf_smooth = float(self.conf)
        self._opposing_streak = 0
        if self.kalman is None:
            self.kalman = KalmanBoxTracker(self.bbox)

    def update_evidence(self, raw_cls: int, raw_conf: float):
        """
        Update continuous posterior probability using Probability EMA & Schmitt trigger.
        Class 1 = child, Class 0 = adult.
        """
        p_obs = float(raw_conf) if raw_cls == 1 else max(0.0, 1.0 - float(raw_conf))
        self.prob_child = self.prob_beta * self.prob_child + (1.0 - self.prob_beta) * p_obs
        self.prob_child = max(0.0, min(1.0, self.prob_child))

        # Dual-threshold Schmitt trigger (asymmetric hysteresis)
        if self.cls == 0:
            if self.prob_child >= self.child_enter_thresh:
                self.cls = 1
        else:
            if self.prob_child <= self.child_exit_thresh:
                self.cls = 0

    def update_class(self, raw_cls: int, switch_threshold: int) -> int:
        """Backward-compatible fallback for callers invoking the older integer streak interface."""
        self.update_evidence(raw_cls, 0.75)
        return self.cls

    @property
    def established(self) -> bool:
        """A track is 'established' once it has been matched for at least ESTABLISHMENT_MIN_HITS frames."""
        return self.hits >= ESTABLISHMENT_MIN_HITS


class DetectionTracker:
    """
    Kalman Filter + ByteTrack Cascaded Association + Probability EMA Consensus Tracker.

    Parameters
    ----------
    iou_threshold : float
        Minimum IoU to consider a detection and track matching (default 0.25).
    max_misses : int
        Consecutive frames an established track survives without matching.
    smooth_alpha : float
        EMA weight for bounding box smoothing (default 0.6).
    conf_smooth_alpha : float
        EMA weight for confidence score smoothing (default 0.4).
    class_switch_frames : int
        Legacy streak threshold (backward compatibility).
    high_conf_thresh : float
        Threshold for ByteTrack Stage 1 high-confidence detections (default 0.50).
    low_conf_thresh : float
        Threshold for ByteTrack Stage 2 low-confidence detections (default 0.20).
    match_thresh_1 : float
        IoU threshold for Stage 1 association (default 0.30).
    match_thresh_2 : float
        IoU threshold for Stage 2 association (default 0.40).
    prob_ema_beta : float
        EMA memory coefficient for probability consensus (default 0.80).
    child_enter_thresh : float
        Schmitt trigger upper threshold to switch to child (default 0.60).
    child_exit_thresh : float
        Schmitt trigger lower threshold to revert to adult (default 0.35).
    """

    def __init__(
        self,
        iou_threshold: float = 0.25,
        max_misses: int = 25,
        smooth_alpha: float = 0.6,
        conf_smooth_alpha: float = 0.4,
        class_switch_frames: int = DEFAULT_CLASS_SWITCH_FRAMES,
        high_conf_thresh: float = 0.50,
        low_conf_thresh: float = 0.20,
        match_thresh_1: float = 0.30,
        match_thresh_2: float = 0.40,
        prob_ema_beta: float = 0.80,
        child_enter_thresh: float = 0.60,
        child_exit_thresh: float = 0.35,
    ):
        self.iou_threshold = float(iou_threshold)
        self.max_misses = int(max_misses)
        self.smooth_alpha = max(0.1, min(1.0, float(smooth_alpha)))
        self.conf_smooth_alpha = max(0.1, min(1.0, float(conf_smooth_alpha)))
        self.class_switch_frames = int(class_switch_frames)

        self.high_conf_thresh = float(high_conf_thresh)
        self.low_conf_thresh = float(low_conf_thresh)
        self.match_thresh_1 = float(match_thresh_1)
        self.match_thresh_2 = float(match_thresh_2)
        self.prob_ema_beta = max(0.1, min(0.99, float(prob_ema_beta)))
        self.child_enter_thresh = float(child_enter_thresh)
        self.child_exit_thresh = float(child_exit_thresh)

        self._tracks: Dict[int, Track] = {}
        self._next_id: int = 1

    def update(self, detections: List[dict]) -> List[dict]:
        """
        Match incoming YOLO detections using ByteTrack cascaded matching
        and return stabilized detections with Kalman predictions for misses.
        """
        try:
            return self._update_internal(detections)
        except Exception:
            # Fail-safe: return raw detections unchanged if anything breaks
            return detections

    def _update_internal(self, detections: List[dict]) -> List[dict]:
        # --- Step 1: Kalman state prediction for all existing tracks ---
        for track in self._tracks.values():
            track.kalman.predict()

        # --- Step 2: Partition detections into high and low confidence tiers ---
        high_dets: List[dict] = []
        low_dets: List[dict] = []
        for det in detections:
            conf = float(det["conf"])
            if conf >= self.high_conf_thresh:
                high_dets.append(det)
            elif conf >= self.low_conf_thresh:
                low_dets.append(det)

        track_list = list(self._tracks.values())

        # --- Step 3: Stage 1 Association (Tracks <-> High Confidence Detections) ---
        matched_pairs_1, unmatched_t_indices_1, unmatched_d_high_indices = _match_boxes(
            track_list, high_dets, self.match_thresh_1
        )

        for t_idx, d_idx in matched_pairs_1:
            track = track_list[t_idx]
            det = high_dets[d_idx]

            # Update Kalman state
            track.kalman.update(det["bbox"])
            track.hits += 1
            track.misses = 0

            # Update Probability EMA class consensus
            track.update_evidence(det["cls"], det["conf"])

            # EMA smooth bounding box
            alpha = self.smooth_alpha
            old = track._bbox_smooth
            new = tuple(float(v) for v in det["bbox"])
            track._bbox_smooth = tuple(
                alpha * n + (1.0 - alpha) * o for n, o in zip(new, old)
            )
            track.bbox = tuple(int(round(v)) for v in track._bbox_smooth)

            # EMA smooth confidence score
            c_alpha = self.conf_smooth_alpha
            track._conf_smooth = (
                c_alpha * det["conf"] + (1.0 - c_alpha) * track._conf_smooth
            )
            track.conf = round(track._conf_smooth, 3)

        # --- Step 4: Stage 2 Association (Remaining Tracks <-> Low Confidence Detections) ---
        unmatched_tracks_stage1 = [track_list[i] for i in unmatched_t_indices_1]
        matched_pairs_2, unmatched_t_indices_2, _ = _match_boxes(
            unmatched_tracks_stage1, low_dets, self.match_thresh_2
        )

        for t_idx, d_idx in matched_pairs_2:
            track = unmatched_tracks_stage1[t_idx]
            det = low_dets[d_idx]

            # Rescued from occlusion / motion blur!
            track.kalman.update(det["bbox"])
            track.hits += 1
            track.misses = 0

            # Update class consensus with lower weight
            track.update_evidence(det["cls"], det["conf"])

            alpha = self.smooth_alpha
            old = track._bbox_smooth
            new = tuple(float(v) for v in det["bbox"])
            track._bbox_smooth = tuple(
                alpha * n + (1.0 - alpha) * o for n, o in zip(new, old)
            )
            track.bbox = tuple(int(round(v)) for v in track._bbox_smooth)

            c_alpha = self.conf_smooth_alpha
            track._conf_smooth = (
                c_alpha * det["conf"] + (1.0 - c_alpha) * track._conf_smooth
            )
            track.conf = round(track._conf_smooth, 3)

        # --- Step 5: Advance misses for remaining unmatched tracks ---
        still_unmatched_tracks = [unmatched_tracks_stage1[i] for i in unmatched_t_indices_2]
        for track in still_unmatched_tracks:
            track.misses += 1
            # Ghost persistence: propagate position using Kalman prediction
            track.bbox = track.kalman.last_predicted_bbox
            track._bbox_smooth = tuple(float(v) for v in track.bbox)
            # Gentle confidence decay during occluded/ghost frames
            track.conf = round(max(0.1, track.conf * 0.96), 3)

        # --- Step 6: Initialize new tracks from unmatched HIGH-confidence detections ---
        for d_idx in unmatched_d_high_indices:
            det = high_dets[d_idx]
            tid = self._next_id
            self._next_id += 1

            p_initial = (
                float(det["conf"])
                if det["cls"] == 1
                else max(0.0, 1.0 - float(det["conf"]))
            )
            self._tracks[tid] = Track(
                track_id=tid,
                bbox=det["bbox"],
                conf=det["conf"],
                cls=det["cls"],
                hits=1,
                misses=0,
                prob_child=p_initial,
                prob_beta=self.prob_ema_beta,
                child_enter_thresh=self.child_enter_thresh,
                child_exit_thresh=self.child_exit_thresh,
            )

        # --- Step 7: Expire tracks (establishment-gated) ---
        expired = []
        for tid, t in self._tracks.items():
            if t.established:
                if t.misses > self.max_misses:
                    expired.append(tid)
            else:
                if t.misses > 1:
                    expired.append(tid)
        for tid in expired:
            del self._tracks[tid]

        # --- Step 8: Build output (active tracks, including Kalman ghosts) ---
        output: List[dict] = []
        for track in self._tracks.values():
            output.append({
                "bbox": track.bbox,
                "conf": track.conf,
                "cls": track.cls,
                "track_id": track.track_id,
            })

        return output
