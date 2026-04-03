"""
prelabel_persons.py
Run our fine-tuned best.pt model on selected frames to detect adult and child instances.
Export as Label Studio JSON import format for pre-annotation.
"""

import json
from pathlib import Path
from ultralytics import YOLO

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
FRAMES_DIR = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "raw_frames" / "batch_301_319"
OUTPUT_JSON = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "annotation_exports" / "prelabels_batch_301_319.json"
MODEL_PATH = PROJECT_ROOT / "datasets" / "merged_dataset_v1" / "trained_model" / "weights" / "best.pt"
CONFIDENCE_THRESHOLD = 0.50  # Using our validated exact dashboard conf threshold
IOU_THRESHOLD = 0.45         # Using our validated dashboard iou
# ───────────────────────────────────────────────────────────────

OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

# Load our retrained model instead of generic COCO YOLOv8n
model = YOLO(str(MODEL_PATH))

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
    # Run prediction specifically mimicking our cv_inference parameters!
    results = model(str(img_path), verbose=False, conf=CONFIDENCE_THRESHOLD, iou=IOU_THRESHOLD, agnostic_nms=True)
    result = results[0]

    img_w = result.orig_shape[1]
    img_h = result.orig_shape[0]

    annotations = []
    
    if result.boxes is not None and len(result.boxes) > 0:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            
            # Map exactly to YOLO classes: 0 = adult, 1 = child
            label_name = "adult" if cls_id == 0 else "child"
                
            conf = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()

            # Convert to Label Studio format (percentages relative to pure width/height)
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

    # Frame paths served on localhost:8095
    # The image path assumes the server is hosted from the raw_frames directory root.
    # Therefore the folder segment is "batch_301_319/" + image name
    task = {
        "data": {
            "image": f"http://localhost:8095/{FRAMES_DIR.name}/{img_path.name}"
        },
        "predictions": [
            {
                "model_version": "Dashboard-Fine-Tuned-merged_dataset_v1",
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

# Write out the JSON task file for Label Studio
with open(OUTPUT_JSON, "w") as f:
    json.dump(ls_tasks, f, indent=2)

print(f"\n{'='*50}")
print(f"Total images processed: {len(ls_tasks)}")
print(f"Total adult/child detections: {total_detections}")
print(f"Average per image: {total_detections / max(len(ls_tasks), 1):.1f}")
print(f"Output saved: {OUTPUT_JSON}")
