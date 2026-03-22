"""
prelabel_persons.py
Run pretrained YOLOv8n on selected frames to detect all "person" instances.
Export as Label Studio JSON import format for pre-annotation.
"""

import json
from pathlib import Path
from ultralytics import YOLO

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
FRAMES_DIR = PROJECT_ROOT / "datasets" / "afternoon_v1" / "frames_selected" / "201-250"
OUTPUT_JSON = PROJECT_ROOT / "datasets" / "afternoon_v1" / "exports" / "prelabels_201_250.json"
CONFIDENCE_THRESHOLD = 0.3  # Lower threshold to catch more people
# ───────────────────────────────────────────────────────────────

OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

# Load pretrained YOLOv8n (COCO)
model = YOLO("yolov8n.pt")

image_files = sorted(
    list(FRAMES_DIR.glob("*.jpg"))
    + list(FRAMES_DIR.glob("*.png"))
)

print(f"Found {len(image_files)} images in {FRAMES_DIR}")
print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}")
print(f"Output: {OUTPUT_JSON}\n")

ls_tasks = []
total_detections = 0

for img_path in image_files:
    results = model(str(img_path), verbose=False, conf=CONFIDENCE_THRESHOLD)
    result = results[0]

    img_w = result.orig_shape[1]
    img_h = result.orig_shape[0]

    annotations = []
    for box in result.boxes:
        cls_id = int(box.cls[0])
        if cls_id != 0:  # Only "person" class (COCO class 0)
            continue

        conf = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()

        # Convert to Label Studio format (percentages)
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
                "rectanglelabels": ["adult"]
            },
            "score": round(conf, 4)
        })

    total_detections += len(annotations)

    task = {
        "data": {
            "image": f"http://localhost:8095/{FRAMES_DIR.name}/{img_path.name}"
        },
        "predictions": [
            {
                "model_version": "yolov8n-coco",
                "score": round(
                    sum(a["score"] for a in annotations) / max(len(annotations), 1), 4
                ),
                "result": annotations
            }
        ]
    }

    ls_tasks.append(task)
    det_count = len(annotations)
    print(f"  {img_path.name}: {det_count} person(s) detected")

# Write JSON
with open(OUTPUT_JSON, "w") as f:
    json.dump(ls_tasks, f, indent=2)

print(f"\n{'='*50}")
print(f"Total images: {len(ls_tasks)}")
print(f"Total person detections: {total_detections}")
print(f"Average per image: {total_detections / max(len(ls_tasks), 1):.1f}")
print(f"Output saved: {OUTPUT_JSON}")
