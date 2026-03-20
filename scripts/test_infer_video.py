from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from cv_inference import ChildLikeDetector, ROI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a quick inference sanity check on a manual dataset video."
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to the trained manual-model weights (.pt)",
    )
    parser.add_argument(
        "--video",
        required=True,
        help="Path to a local video file for validation",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.65,
        help="Child confidence threshold (default: 0.65)",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=30,
        help="Print one output dict every N frames (default: 30)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = Path(args.model)
    video_path = Path(args.video)

    if not model_path.exists():
        raise SystemExit(f"Model not found: {model_path}")
    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")

    detector = ChildLikeDetector(str(model_path), conf_child=args.conf)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video_path}")

    printed = 0
    roi = None

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if roi is None:
            height, width = frame.shape[:2]
            roi = ROI(x1=0, y1=0, x2=width - 1, y2=height - 1)
            print(f"Frame resolution: {width}x{height}")

        out = detector.infer_frame(frame, roi)
        printed += 1
        if printed % max(1, args.sample_every) == 0:
            print(f"Frame {printed}: {out}")

    cap.release()
    print("Inference check complete.")


if __name__ == "__main__":
    main()
