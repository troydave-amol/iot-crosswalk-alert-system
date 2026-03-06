import unittest

import numpy as np

from cv_inference import ChildLikeDetector, ROI, _bbox_iou
import warning_controller
from warning_controller import TemporalVoteStabilizer, WarningController


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


class _FakeModel:
    def __init__(self, result):
        self._result = result
        self.last_predict_kwargs = None

    def predict(self, **kwargs):
        self.last_predict_kwargs = kwargs
        return [self._result]


class _TimeSequence:
    def __init__(self, values):
        self._values = iter(values)
        self._original_time_fn = None

    def __enter__(self):
        self._original_time_fn = warning_controller.time.time
        warning_controller.time.time = lambda: next(self._values)
        return self

    def __exit__(self, exc_type, exc, tb):
        warning_controller.time.time = self._original_time_fn
        return False


def _build_detector(fake_model, conf_child=0.65, min_child_bbox_ratio=0.18, dominance_iou=0.70):
    detector = ChildLikeDetector.__new__(ChildLikeDetector)
    detector.model_path = "fake.pt"
    detector.conf_child = conf_child
    detector.model = fake_model
    detector.device = None
    detector.min_child_bbox_ratio = min_child_bbox_ratio
    detector.dominance_iou = dominance_iou
    detector.imgsz = 640
    return detector


class DetectorHardeningTests(unittest.TestCase):
    def test_predict_uses_agnostic_nms_and_iou_060(self):
        boxes = _FakeBoxes(
            xyxy=[[10, 10, 120, 300]],
            conf=[0.9],
            cls=[0],
        )
        fake_model = _FakeModel(_FakeResult(boxes))
        detector = _build_detector(fake_model)

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        roi = ROI(0, 0, 1279, 719)
        detector.infer_frame(frame, roi)

        self.assertIsNotNone(fake_model.last_predict_kwargs)
        self.assertTrue(fake_model.last_predict_kwargs["agnostic_nms"])
        self.assertEqual(fake_model.last_predict_kwargs["iou"], 0.60)

    def test_adult_like_never_triggers_child_raw(self):
        boxes = _FakeBoxes(
            xyxy=[[100, 100, 200, 260]],  # height 160
            conf=[0.95],
            cls=[1],  # adult_like
        )
        fake_model = _FakeModel(_FakeResult(boxes))
        detector = _build_detector(fake_model)

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        roi = ROI(0, 0, 1279, 719)
        out = detector.infer_frame(frame, roi)

        self.assertFalse(out["child_in_roi_raw"])
        self.assertEqual(out["confidence_raw"], 0.0)

    def test_small_child_below_min_ratio_does_not_trigger(self):
        boxes = _FakeBoxes(
            xyxy=[[100, 100, 220, 220]],  # height 120, below 0.18*720=129.6
            conf=[0.90],
            cls=[0],
        )
        fake_model = _FakeModel(_FakeResult(boxes))
        detector = _build_detector(fake_model)

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        roi = ROI(0, 0, 1279, 719)
        out = detector.infer_frame(frame, roi)

        self.assertFalse(out["child_in_roi_raw"])
        self.assertEqual(out["confidence_raw"], 0.0)
        self.assertEqual(len(out["detections"]), 1)  # raw drawing data remains present


class StabilizerTests(unittest.TestCase):
    def test_three_of_five_true_sequence(self):
        s = TemporalVoteStabilizer(window_size=5, required_true=3)
        seq = [
            (True, 0.61),
            (False, 0.00),
            (True, 0.72),
            (False, 0.00),
            (True, 0.83),
        ]
        last_state = None
        for child, conf in seq:
            last_state = s.update(child, conf)
        self.assertEqual(last_state, (True, 0.83))

    def test_three_of_five_false_sequence(self):
        s = TemporalVoteStabilizer(window_size=5, required_true=3)
        seq = [
            (True, 0.70),
            (False, 0.00),
            (False, 0.00),
            (False, 0.00),
            (True, 0.90),
        ]
        last_state = None
        for child, conf in seq:
            last_state = s.update(child, conf)
        self.assertEqual(last_state, (False, 0.0))


class DominanceIoUTests(unittest.TestCase):
    def test_high_and_low_overlap_iou_threshold_examples(self):
        high_overlap_a = (100.0, 100.0, 220.0, 300.0)
        high_overlap_b = (110.0, 110.0, 230.0, 310.0)
        low_overlap = (400.0, 120.0, 520.0, 320.0)

        self.assertGreaterEqual(_bbox_iou(high_overlap_a, high_overlap_b), 0.70)
        self.assertLess(_bbox_iou(high_overlap_a, low_overlap), 0.70)


class WarningControllerTests(unittest.TestCase):
    def test_hold_keeps_warning_on_then_allows_off(self):
        wc = WarningController(hold_seconds=2.0, min_toggle_interval_sec=0.0)
        with _TimeSequence([1.0, 2.0, 3.2]):
            self.assertTrue(wc.update(True))   # turns ON
            self.assertTrue(wc.update(False))  # still ON due to hold
            self.assertFalse(wc.update(False))  # hold elapsed -> OFF

    def test_min_toggle_interval_blocks_rapid_flip(self):
        wc = WarningController(hold_seconds=0.0, min_toggle_interval_sec=0.75)
        with _TimeSequence([1.0, 1.2, 1.9]):
            self.assertTrue(wc.update(True))    # ON
            self.assertTrue(wc.update(False))   # blocked by min toggle interval
            self.assertFalse(wc.update(False))  # enough time elapsed -> OFF


if __name__ == "__main__":
    unittest.main()
