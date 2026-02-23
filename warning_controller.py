from __future__ import annotations
import time
from dataclasses import dataclass

@dataclass
class WarningState:
    warning_requested: bool
    last_child_seen_ts: float

class WarningController:
    """
    Converts raw child_in_roi into a stable warning_requested signal.

    Rules:
    - If child_in_roi is True -> warning_requested True immediately
    - If child_in_roi becomes False -> keep warning ON for hold_seconds
    """
    def __init__(self, hold_seconds: float = 2.0):
        self.hold_seconds = float(hold_seconds)
        self.state = WarningState(warning_requested=False, last_child_seen_ts=0.0)

    def update(self, child_in_roi: bool) -> bool:
        now = time.time()

        if child_in_roi:
            self.state.last_child_seen_ts = now
            self.state.warning_requested = True
            return True

        # child not in ROI now -> allow hold
        if self.state.warning_requested:
            if (now - self.state.last_child_seen_ts) <= self.hold_seconds:
                return True
            self.state.warning_requested = False

        return False
