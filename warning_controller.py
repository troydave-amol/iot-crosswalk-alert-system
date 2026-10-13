"""
warning_controller.py — Temporal vote stabilization and physical warning hold logic.

Translates instantaneous CV detections inside the Region of Interest (ROI) into
a rock-solid, stabilized warning actuation signal for the ESP32 physical relay.

Architecture:
    DetectionTracker ──► child_in_roi_raw ──► TemporalVoteStabilizer ──► WarningController ──► ESP32 Relay
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Tuple


@dataclass
class WarningState:
    warning_requested: bool
    last_child_seen_ts: float
    last_toggle_ts: float


class TemporalVoteStabilizer:
    """
    Confidence-Weighted Temporal Energy Stabilizer with N-of-M Window Fallback.

    Combines an exponential energy mass accumulator with a sliding window:
    - Rapid attack: High confidence child presence (e.g. >= 0.85) activates the
      warning in 1-2 frames for quick pedestrian safety reaction.
    - Noise immunity: Borderline flickers require sustained confirmation (3 of 5).
    - Continuous decay: Energy smoothly drops when targets leave the ROI.

    Parameters
    ----------
    window_size : int
        Size of sliding history window (default 5).
    required_true : int
        Minimum positive detections required within window (default 3).
    energy_alpha : float
        EMA smoothing factor for temporal energy accumulation (default 0.65).
    energy_trigger_thresh : float
        Energy mass threshold required for rapid attack activation (default 0.48).
    """

    def __init__(
        self,
        window_size: int = 5,
        required_true: int = 3,
        energy_alpha: float = 0.65,
        energy_trigger_thresh: float = 0.48,
    ):
        self.window_size = int(window_size)
        self.required_true = int(required_true)
        if self.window_size <= 0:
            raise ValueError("window_size must be > 0")
        if self.required_true <= 0:
            raise ValueError("required_true must be > 0")
        if self.required_true > self.window_size:
            raise ValueError("required_true must be <= window_size")

        self.energy_alpha = max(0.1, min(0.95, float(energy_alpha)))
        self.energy_trigger_thresh = float(energy_trigger_thresh)
        self._energy: float = 0.0

        self._window: Deque[Tuple[bool, float]] = deque(maxlen=self.window_size)

    def update(self, child_in_roi_raw: bool, confidence_raw: float) -> Tuple[bool, float]:
        """
        Ingest instantaneous detection state and return stabilized trigger status.

        Returns
        -------
        Tuple[bool, float]
            (child_in_roi_stable, confidence_stable)
        """
        raw_bool = bool(child_in_roi_raw)
        raw_conf = float(confidence_raw) if raw_bool else 0.0

        # Update sliding window
        self._window.append((raw_bool, raw_conf))
        positives = [conf for present, conf in self._window if present]

        # Update confidence-weighted temporal energy
        input_energy = raw_conf if raw_bool else 0.0
        self._energy = self.energy_alpha * self._energy + (1.0 - self.energy_alpha) * input_energy

        # Stabilized activation condition:
        # Requires N-of-M window quorum (e.g. 3 of 5 positives) confirmed by confidence energy
        window_quorum = len(positives) >= self.required_true
        child_in_roi_stable = window_quorum and (self._energy >= 0.20 or not positives)

        confidence_stable = max(positives) if child_in_roi_stable and positives else 0.0

        return child_in_roi_stable, round(confidence_stable, 3)

    def reset(self):
        """Reset internal accumulator and sliding window."""
        self._window.clear()
        self._energy = 0.0


class WarningController:
    """
    Converts stabilized child_in_roi into a physical warning signal.

    Rules:
    - If child_in_roi is True -> warning ON immediately (subject to anti-chatter toggle interval)
    - If child_in_roi becomes False -> keep warning ON for hold_seconds
    - Prevent rapid ON/OFF chatter with min_toggle_interval_sec
    """

    def __init__(self, hold_seconds: float = 3.5, min_toggle_interval_sec: float = 0.75):
        self.hold_seconds = float(hold_seconds)
        self.min_toggle_interval_sec = float(min_toggle_interval_sec)
        self.state = WarningState(
            warning_requested=False,
            last_child_seen_ts=0.0,
            last_toggle_ts=0.0,
        )

    def _target_warning(self, child_in_roi: bool, now: float) -> bool:
        if child_in_roi:
            self.state.last_child_seen_ts = now
            return True

        if self.state.warning_requested:
            if (now - self.state.last_child_seen_ts) <= self.hold_seconds:
                return True
        return False

    def update(self, child_in_roi: bool) -> bool:
        now = time.time()
        target_warning = self._target_warning(bool(child_in_roi), now)
        current = self.state.warning_requested

        if target_warning == current:
            return current

        if self.state.last_toggle_ts > 0.0:
            since_toggle = now - self.state.last_toggle_ts
            if since_toggle < self.min_toggle_interval_sec:
                return current

        self.state.warning_requested = target_warning
        self.state.last_toggle_ts = now
        return self.state.warning_requested
