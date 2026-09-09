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
    Stabilizes detector output with an N-of-M vote.
    """

    def __init__(self, window_size: int = 5, required_true: int = 3):
        self.window_size = int(window_size)
        self.required_true = int(required_true)
        if self.window_size <= 0:
            raise ValueError("window_size must be > 0")
        if self.required_true <= 0:
            raise ValueError("required_true must be > 0")
        if self.required_true > self.window_size:
            raise ValueError("required_true must be <= window_size")
        self._window: Deque[Tuple[bool, float]] = deque(maxlen=self.window_size)

    def update(self, child_in_roi_raw: bool, confidence_raw: float) -> Tuple[bool, float]:
        self._window.append((bool(child_in_roi_raw), float(confidence_raw)))
        positives = [conf for present, conf in self._window if present]
        child_in_roi_stable = len(positives) >= self.required_true
        confidence_stable = max(positives) if child_in_roi_stable else 0.0
        return child_in_roi_stable, round(confidence_stable, 3)


class WarningController:
    """
    Converts stabilized child_in_roi into a warning signal.

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
