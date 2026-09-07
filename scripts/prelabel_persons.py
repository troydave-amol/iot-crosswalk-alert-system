"""
prelabel_persons.py
────────────────────────────────────────────────────────────────
Runs the fine-tuned YOLOv8 model (yolov8n_crosswalk_v2_1111_frames.pt)
on frame batches in 'datasets/August 11, 2026 Frames/' to pre-detect
adult (0) and child (1) instances.

Exports predictions into Label Studio JSON import format.
"""

import argparse
import json
from pathlib import Path
from ultralytics import YOLO

# ── Defaults & Configuration ────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
BASE_DATASET_DIR = PROJECT_ROOT / "datasets" / "August 11, 2026 Frames"
EXPORTS_DIR = BASE_DATASET_DIR / "annotation_exports"
MODEL_PATH = PROJECT_ROOT / "models" / "yolov8n_1500_frames.pt"

CONFIDENCE_THRESHOLD = 0.50  # Matches cv_inference.py stringency
IOU_THRESHOLD = 0.45         # Aggressive NMS to eliminate duplicate boxes
# ───────────────────────────────────────────────────────────────


def prelabel_batch(model: YOLO, batch_dir: Path, output_json: Path):
    image_files = sorted(
        list(batch_dir.glob("*.jpg"))
        + list(batch_dir.glob("*.png"))
    )

    if not image_files:
        print(f"[WARN] No image files found in {batch_dir}")
        return 0, 0

    print(f"\nProcessing {batch_dir.name} ({len(image_files)} images)")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}")
    print(f"Output: {output_json}\n")

    ls_tasks = []
    total_detections = 0
    adult_count = 0
    child_count = 0

    for img_path in image_files:
        # Run inference mimicking runtime cv_inference parameters
        results = model(
            str(img_path),
            verbose=False,
            conf=CONFIDENCE_THRESHOLD,
            iou=IOU_THRESHOLD,
            agnostic_nms=True
        )
        result = results[0]

        img_w = result.orig_shape[1]
        img_h = result.orig_shape[0]

        annotations = []

        if result.boxes is not None and len(result.boxes) > 0:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                # Canonical mapping: 0 = adult, 1 = child
                label_name = "adult" if cls_id == 0 else "child"
                if cls_id == 0:
                    adult_count += 1
                else:
                    child_count += 1

                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # Label Studio format uses percentage coords
                x_pct = (x1 / img_w) * 100
                y_pct = (y1 / img_h) * 100
                w_pct = ((x2 - x1) / img_w) * 100
                h_pct = ((y2 - y1) / img_h) * 100

                annotations.append({
                    "id": f"{img_path.stem}_{len(annotations)}",
                    "type": "rectanglelabels",
                    "from_name": "label",
                    "to_name": "image",
                    "original_width": img_w,
                    "original_height": img_h,
                    "value": {
                        "x": round(x_pct, 2),
                        "y": round(y_pct, 2),
                        "width": round(w_pct, 2),
                        "height": round(h_pct, 2),
                        "rotation": 0,
                        "rectanglelabels": [label_name]
                    },
                    "score": round(conf, 4)
                })

        total_detections += len(annotations)

        # Image URL served by scripts/serve_frames.py on localhost:8095
        task = {
            "data": {
                "image": f"http://localhost:8095/{batch_dir.name}/{img_path.name}"
            },
            "predictions": [
                {
                    "model_version": "yolov8n_1500_frames",
                    "score": round(
                        sum(a["score"] for a in annotations) / max(len(annotations), 1), 4
                    ) if annotations else 0.0,
                    "result": annotations
                }
            ]
        }

        ls_tasks.append(task)
        det_count = len(annotations)
        print(f"  {img_path.name}: {det_count} detection(s)")

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(ls_tasks, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Summary for {batch_dir.name}:")
    print(f"  Total images processed : {len(ls_tasks)}")
    print(f"  Total detections       : {total_detections} (adult: {adult_count}, child: {child_count})")
    print(f"  Average per image      : {total_detections / max(len(ls_tasks), 1):.1f}")
    print(f"  Output saved           : {output_json}")
    print(f"{'='*50}\n")

    return len(ls_tasks), total_detections


def main():
    parser = argparse.ArgumentParser(description="Pre-label frame batches with YOLOv8 for Label Studio.")
    parser.add_argument(
        "--batch",
        type=str,
        default="all",
        help="Batch folder name (e.g. 'batch_015') or 'all' to process all batches."
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting batch number (e.g. 15 for batch_015)."
    )
    parser.add_argument(
        "--end",
        type=int,
        default=57,
        help="Ending batch number (e.g. 57 for batch_057)."
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip batches that already have a prelabels JSON file (default: True)."
    )
    args = parser.parse_args()

    print(f"Loading YOLO model from: {MODEL_PATH}")
    if not MODEL_PATH.exists():
        print(f"[ERROR] Model checkpoint not found: {MODEL_PATH}")
        return

    model = YOLO(str(MODEL_PATH))

    if args.batch == "all":
        batch_dirs = sorted([d for d in BASE_DATASET_DIR.iterdir() if d.is_dir() and d.name.startswith("batch_")])
        print(f"Found {len(batch_dirs)} total batch folders in {BASE_DATASET_DIR}")
        
        # Filter by start/end range if specified
        filtered_dirs = []
        for d in batch_dirs:
            try:
                b_num = int(d.name.split("_")[1])
                if args.start <= b_num <= args.end:
                    filtered_dirs.append(d)
            except (IndexError, ValueError):
                filtered_dirs.append(d)
                
        print(f"Processing range batch_{args.start:03d} to batch_{args.end:03d} ({len(filtered_dirs)} batches)\n")
        
        for bdir in filtered_dirs:
            out_json = EXPORTS_DIR / f"prelabels_{bdir.name}.json"
            if args.skip_existing and out_json.exists():
                print(f"[SKIP] {bdir.name}: {out_json.name} already exists.")
                continue
            prelabel_batch(model, bdir, out_json)
    else:
        target_dir = BASE_DATASET_DIR / args.batch
        if not target_dir.exists():
            print(f"[ERROR] Batch directory does not exist: {target_dir}")
            return
        out_json = EXPORTS_DIR / f"prelabels_{args.batch}.json"
        prelabel_batch(model, target_dir, out_json)


if __name__ == "__main__":
    main()

