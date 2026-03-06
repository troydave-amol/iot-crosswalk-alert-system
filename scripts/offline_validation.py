from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import warning_controller
from cv_inference import ChildLikeDetector, ROI
from warning_controller import TemporalVoteStabilizer, WarningController


FRAME_W = 1280
FRAME_H = 720
ROI_TEST = ROI(x1=300, y1=180, x2=980, y2=700)


class _FakeTensor:
    def __init__(self, values):
        self._values = np.array(values, dtype=float)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class _FakeBoxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = _FakeTensor(xyxy)
        self.conf = _FakeTensor(conf)
        self.cls = _FakeTensor(cls)

    def __len__(self):
        return len(self.conf.numpy())


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FrameModel:
    """
    Deterministic frame-by-frame model that returns predefined detections.
    Each frame is a list of dicts: {"bbox": (x1,y1,x2,y2), "conf": float, "cls": int}
    """

    def __init__(self, frame_detections: List[List[Dict]]):
        self._frames = frame_detections
        self._idx = 0

    def predict(self, **kwargs):
        if self._idx >= len(self._frames):
            detections = []
        else:
            detections = self._frames[self._idx]
        self._idx += 1

        if not detections:
            boxes = _FakeBoxes(xyxy=[], conf=[], cls=[])
            return [_FakeResult(boxes)]

        xyxy = [d["bbox"] for d in detections]
        conf = [d["conf"] for d in detections]
        cls = [d["cls"] for d in detections]
        boxes = _FakeBoxes(xyxy=xyxy, conf=conf, cls=cls)
        return [_FakeResult(boxes)]


@dataclass
class CaseResult:
    name: str
    passed: bool
    reason: str
    frames: List[Dict]


def _build_detector(fake_model) -> ChildLikeDetector:
    detector = ChildLikeDetector.__new__(ChildLikeDetector)
    detector.model_path = "synthetic.pt"
    detector.conf_child = 0.65
    detector.model = fake_model
    detector.device = None
    detector.min_child_bbox_ratio = 0.18
    detector.dominance_iou = 0.70
    detector.imgsz = 640
    return detector


def _det(
    cls: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    conf: float,
) -> Dict:
    return {"cls": cls, "bbox": (x1, y1, x2, y2), "conf": float(conf)}


def _run_sequence(
    frame_detections: List[List[Dict]],
    dt_seconds: float = 0.25,
) -> List[Dict]:
    model = _FrameModel(frame_detections)
    detector = _build_detector(model)
    stabilizer = TemporalVoteStabilizer(window_size=5, required_true=3)
    warn_ctrl = WarningController(hold_seconds=2.0, min_toggle_interval_sec=0.75)

    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    t0 = 1000.0
    times = [t0 + i * dt_seconds for i in range(len(frame_detections))]

    original_time_fn = warning_controller.time.time
    results: List[Dict] = []
    time_iter = iter(times)
    warning_controller.time.time = lambda: next(time_iter)
    try:
        for idx in range(len(frame_detections)):
            raw = detector.infer_frame(frame, ROI_TEST)
            child_stable, conf_stable = stabilizer.update(
                raw.get("child_in_roi_raw", False),
                raw.get("confidence_raw", 0.0),
            )
            warning_on = warn_ctrl.update(child_stable)

            results.append(
                {
                    "i": idx,
                    "t": round(times[idx], 3),
                    "raw": bool(raw.get("child_in_roi_raw", False)),
                    "stable": bool(child_stable),
                    "warning": bool(warning_on),
                    "confidence_raw": float(raw.get("confidence_raw", 0.0)),
                    "confidence": float(conf_stable),
                }
            )
    finally:
        warning_controller.time.time = original_time_fn

    return results


def _first_index(rows: Iterable[Dict], key: str, value: bool) -> Optional[int]:
    for row in rows:
        if bool(row[key]) == bool(value):
            return int(row["i"])
    return None


def _case_1_adult_enters_roi() -> CaseResult:
    adult = _det(cls=1, x1=510, y1=260, x2=680, y2=680, conf=0.95)
    seq = [[] for _ in range(5)] + [[adult] for _ in range(12)]
    rows = _run_sequence(seq)

    adult_window = rows[5:]
    passed = all((not r["raw"]) and (not r["stable"]) and (not r["warning"]) for r in adult_window)
    reason = (
        "adult-like detections never triggered raw/stable/warning"
        if passed
        else "adult-only frames triggered child pipeline unexpectedly"
    )
    return CaseResult("1) Adult enters ROI", passed, reason, rows)


def _case_2_child_enters_full_body() -> CaseResult:
    child = _det(cls=0, x1=560, y1=330, x2=660, y2=690, conf=0.88)
    seq = (
        [[] for _ in range(3)]
        + [[child], [], [child], [child], [child]]
        + [[child] for _ in range(4)]
    )
    rows = _run_sequence(seq)

    first_raw_true = _first_index(rows, "raw", True)
    first_stable_true = _first_index(rows, "stable", True)
    first_warning_true = _first_index(rows, "warning", True)

    passed = (
        first_raw_true is not None
        and first_stable_true is not None
        and first_warning_true is not None
        and first_stable_true >= 5
        and first_warning_true >= first_stable_true
    )
    reason = (
        f"raw@{first_raw_true}, stable@{first_stable_true}, warning@{first_warning_true}"
        if passed
        else "child-full-body did not promote raw->stable->warning as expected"
    )
    return CaseResult("2) Child enters ROI (full body)", passed, reason, rows)


def _case_3_child_exits_roi() -> CaseResult:
    child = _det(cls=0, x1=560, y1=330, x2=660, y2=690, conf=0.87)
    seq = [[child] for _ in range(8)] + [[] for _ in range(20)]
    rows = _run_sequence(seq)

    last_stable_true = max((r["i"] for r in rows if r["stable"]), default=None)
    first_stable_false_after_true = next(
        (r["i"] for r in rows if (last_stable_true is not None and r["i"] > last_stable_true and not r["stable"])),
        None,
    )
    first_warning_false_after_true = next(
        (r["i"] for r in rows if (last_stable_true is not None and r["i"] > last_stable_true and not r["warning"])),
        None,
    )

    if last_stable_true is None or first_stable_false_after_true is None or first_warning_false_after_true is None:
        return CaseResult(
            "3) Child exits ROI",
            False,
            "could not observe complete stable-true -> stable-false -> warning-off transition",
            rows,
        )

    t_last_true = rows[last_stable_true]["t"]
    t_warning_off = rows[first_warning_false_after_true]["t"]
    hold_elapsed = float(t_warning_off) - float(t_last_true)
    hold_ok = hold_elapsed >= 2.0

    maintained_during_hold = all(
        r["warning"]
        for r in rows
        if (r["i"] > last_stable_true and float(r["t"]) < (float(t_last_true) + 2.0))
    )

    passed = hold_ok and maintained_during_hold
    reason = (
        f"last_stable_true@{last_stable_true}, warning_off@{first_warning_false_after_true}, hold={hold_elapsed:.2f}s"
        if passed
        else f"hold behavior mismatch (hold={hold_elapsed:.2f}s, maintained={maintained_during_hold})"
    )
    return CaseResult("3) Child exits ROI", passed, reason, rows)


def _case_4_group_of_children() -> CaseResult:
    # valid child (full body in ROI)
    child_a = _det(cls=0, x1=520, y1=320, x2=620, y2=690, conf=0.90)
    # near-duplicate child (dominance IoU should remove as trigger duplicate)
    child_b = _det(cls=0, x1=530, y1=330, x2=630, y2=700, conf=0.83)
    adult = _det(cls=1, x1=700, y1=260, x2=860, y2=690, conf=0.96)
    # leg-only / too small: height=80 (< 0.18 * 720 = 129.6)
    child_leg_only = _det(cls=0, x1=600, y1=600, x2=680, y2=680, conf=0.91)

    seq = (
        [[] for _ in range(4)]
        + [[child_a, child_b, adult, child_leg_only] for _ in range(8)]
        + [[adult, child_leg_only] for _ in range(8)]
        + [[child_a, adult, child_leg_only] for _ in range(8)]
    )
    rows = _run_sequence(seq)

    noise_only_block = rows[12:20]  # block with adult + leg-only child only
    leg_only_never_raw = all(not r["raw"] for r in noise_only_block)

    stable_values = [bool(r["stable"]) for r in rows]
    transitions = sum(1 for i in range(1, len(stable_values)) if stable_values[i] != stable_values[i - 1])
    low_flip_count = transitions <= 3

    passed = leg_only_never_raw and low_flip_count
    reason = (
        f"transitions={transitions}, leg_only_raw=false"
        if passed
        else f"unexpected flicker or leg-only trigger (transitions={transitions}, leg_only_ok={leg_only_never_raw})"
    )
    return CaseResult("4) Group of children", passed, reason, rows)


def _case_5_adult_plus_child_together() -> CaseResult:
    adult = _det(cls=1, x1=710, y1=260, x2=860, y2=690, conf=0.97)
    child = _det(cls=0, x1=540, y1=330, x2=640, y2=690, conf=0.89)

    adult_only_frames = 8
    seq = [[adult] for _ in range(adult_only_frames)] + [[adult, child] for _ in range(10)]
    rows = _run_sequence(seq)

    first_warning_true = _first_index(rows, "warning", True)
    warning_before_child = any(r["warning"] for r in rows[:adult_only_frames])
    stable_when_warning_on = all(r["stable"] for r in rows if r["warning"])
    delayed_enable_ok = first_warning_true is not None and first_warning_true >= (adult_only_frames + 2)

    passed = (not warning_before_child) and stable_when_warning_on and delayed_enable_ok
    reason = (
        f"warning_on_first@{first_warning_true}, adult_only_warning=false"
        if passed
        else "warning behavior violated adult+child gating expectations"
    )
    return CaseResult("5) Adult + child together", passed, reason, rows)


def run_step_b_offline() -> List[CaseResult]:
    return [
        _case_1_adult_enters_roi(),
        _case_2_child_enters_full_body(),
        _case_3_child_exits_roi(),
        _case_4_group_of_children(),
        _case_5_adult_plus_child_together(),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline deterministic validator.")
    parser.add_argument("--json", action="store_true", help="Print full JSON output.")
    args = parser.parse_args()

    results = run_step_b_offline()
    any_fail = any(not r.passed for r in results)

    if args.json:
        payload = {
            "overall_pass": not any_fail,
            "cases": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "reason": r.reason,
                    "frames": r.frames,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("Offline Validation")
        print("=" * 26)
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"[{status}] {r.name}: {r.reason}")
        print("-" * 26)
        print(f"OVERALL: {'PASS' if not any_fail else 'FAIL'}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
