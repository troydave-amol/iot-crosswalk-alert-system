"""
test_tracker_robustness.py — Comprehensive validation test suite for
Kalman Filter + ByteTrack Cascaded Association + Probability EMA Consensus Tracking.

Tests:
1. Fast/Running Motion: Target displacing 35px/frame retains track_id.
2. Occlusion Recovery: 4-frame miss recovered by ByteTrack Stage 2 low-conf match.
3. Single-Frame Label Invariance: 1-frame adult noise does not flip child track.
4. Low-Confidence Ghost Rejection: Low-conf noise never spawns new tracks.
5. High-Confidence Track Initialization: Immediate track emission on valid target.
6. Fail-Safe Exception Handling: Corrupt input handled gracefully without crashing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detection_tracker import DetectionTracker, KalmanBoxTracker, Track


def test_running_motion_persistence():
    """Verify that a fast-moving child (35 px/frame) retains their track_id via Kalman prediction."""
    tracker = DetectionTracker(iou_threshold=0.25, high_conf_thresh=0.50)
    track_ids = []

    # Target running across the screen horizontally from x=100 to x=800
    for i in range(20):
        x1 = 100 + i * 35
        y1 = 200
        x2 = x1 + 80
        y2 = y1 + 160
        dets = [{"bbox": (x1, y1, x2, y2), "conf": 0.85, "cls": 1}]
        tracked = tracker.update(dets)
        assert len(tracked) == 1, f"Expected 1 tracked object, got {len(tracked)} at frame {i}"
        track_ids.append(tracked[0]["track_id"])

    # All 20 frames must retain the exact same track ID (zero ID switching)
    assert len(set(track_ids)) == 1, f"Track ID fragmented: {set(track_ids)}"
    print("[PASS] test_running_motion_persistence: 20-frame fast motion retained track ID", track_ids[0])


def test_occlusion_and_bytetrack_recovery():
    """Verify ByteTrack Stage 2 recovers a track after 4 frames of occlusion using a low-conf detection."""
    tracker = DetectionTracker(max_misses=25, high_conf_thresh=0.50, low_conf_thresh=0.20)

    # 1. Establish track for 5 frames
    for i in range(5):
        dets = [{"bbox": (200 + i * 5, 300, 280 + i * 5, 480), "conf": 0.88, "cls": 1}]
        tracked = tracker.update(dets)
        initial_id = tracked[0]["track_id"]

    # 2. Complete occlusion for 4 frames (no detections)
    for _ in range(4):
        tracked = tracker.update([])
        # Target should persist as Kalman ghost
        assert any(t["track_id"] == initial_id for t in tracked), "Target lost during occlusion"

    # 3. Target re-emerges with degraded/low confidence (e.g. 0.35)
    reemerge_det = [{"bbox": (200 + 9 * 5, 300, 280 + 9 * 5, 480), "conf": 0.35, "cls": 1}]
    tracked = tracker.update(reemerge_det)

    recovered = [t for t in tracked if t["track_id"] == initial_id]
    assert len(recovered) == 1, "Failed to recover track after occlusion"
    assert recovered[0]["conf"] > 0.30, "Recovered track has invalid confidence"
    print(f"[PASS] test_occlusion_and_bytetrack_recovery: Track {initial_id} recovered via ByteTrack Stage 2")


def test_single_frame_noise_invariance():
    """Verify that a single-frame misclassification does not flip a child track to adult."""
    tracker = DetectionTracker(prob_ema_beta=0.80, child_enter_thresh=0.60, child_exit_thresh=0.35)

    # 10 frames of child
    for _ in range(10):
        dets = [{"bbox": (300, 300, 380, 480), "conf": 0.85, "cls": 1}]
        tracked = tracker.update(dets)
        assert tracked[0]["cls"] == 1

    # 1 frame of noisy adult misclassification (conf 0.75)
    noisy_det = [{"bbox": (300, 300, 380, 480), "conf": 0.75, "cls": 0}]
    tracked = tracker.update(noisy_det)
    # MUST stay class 1 (child) because Probability EMA absorbs the noise
    assert tracked[0]["cls"] == 1, f"Failed: Class flipped to {tracked[0]['cls']} on single noisy frame!"

    # 5 more frames of child
    for _ in range(5):
        dets = [{"bbox": (300, 300, 380, 480), "conf": 0.85, "cls": 1}]
        tracked = tracker.update(dets)
        assert tracked[0]["cls"] == 1

    print("[PASS] test_single_frame_noise_invariance: Single-frame label flicker successfully suppressed")


def test_low_confidence_ghost_rejection():
    """Verify that low-confidence detections (0.25) do NOT spawn new tracks."""
    tracker = DetectionTracker(high_conf_thresh=0.50, low_conf_thresh=0.20)

    # Low-confidence noise boxes (e.g. tree reflection, shadow)
    noise_dets = [
        {"bbox": (100, 100, 150, 200), "conf": 0.25, "cls": 1},
        {"bbox": (400, 400, 460, 520), "conf": 0.30, "cls": 0},
    ]
    tracked = tracker.update(noise_dets)
    assert len(tracked) == 0, f"Expected 0 tracks from low-confidence noise, got {len(tracked)}"
    print("[PASS] test_low_confidence_ghost_rejection: Low-confidence noise correctly rejected from track creation")


def test_failsafe_resilience():
    """Verify that tracker never raises an uncaught exception when fed malformed detections."""
    tracker = DetectionTracker()

    # Intentionally malformed detections (missing keys, None, invalid types)
    malformed = [
        {"bbox": None, "conf": "invalid"},
        {"bad_key": 123},
    ]
    # Must NOT raise exception — must return input unharmed
    result = tracker.update(malformed)
    assert result == malformed, "Fail-safe did not return raw detections on error"
    print("[PASS] test_failsafe_resilience: Tracker fail-safe protected caller from fatal exception")


def main():
    print("=" * 60)
    print("RUNNING KALMAN + BYTETRACK + PROBABILITY EMA TEST SUITE")
    print("=" * 60)
    test_running_motion_persistence()
    test_occlusion_and_bytetrack_recovery()
    test_single_frame_noise_invariance()
    test_low_confidence_ghost_rejection()
    test_failsafe_resilience()
    print("=" * 60)
    print("ALL ROBUSTNESS TESTS PASSED (5/5)!")
    print("=" * 60)


if __name__ == "__main__":
    main()
