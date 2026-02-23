# YOLOv8 Training Plan

## Model

- Base: `yolov8n.pt` (nano — lightweight for edge/IoT deployment)
- Framework: Ultralytics YOLOv8
- Task: Object detection (single class: `child`)

---

## Phase 1: Baseline (Person Detection)

Train on CityPersons + JAAD to establish a strong pedestrian detector.

```yaml
# datasets/citypersons.yaml or jaad.yaml
model: yolov8n.pt
data: datasets/citypersons.yaml
epochs: 50
imgsz: 640
batch: 16
workers: 2  # CRITICAL: leave at 2 to prevent pagefile OOM on Windows
device: 0  # GPU if available
```

**Output**: `runs/detect/train/weights/best.pt`
Already completed — see `runs/detect/train/` for curves and metrics.

---

## Phase 2: Child-Class Fine-Tuning

Fine-tune baseline on child-labeled dataset.

```yaml
model: runs/detect/train/weights/best.pt  # from Phase 1
data: datasets/crosswalk_child.yaml
epochs: 30
imgsz: 640
batch: 16
freeze: 10  # freeze early backbone layers
```

---

## Evaluation Targets (for Manuscript)

| Metric | Target |
|---|---|
| Precision | >= 0.80 |
| Recall | >= 0.75 |
| mAP@0.5 | >= 0.80 |
| Latency (inference) | <= 100ms per frame |

---

## Evaluation Artifacts (Required for Submission)

- `BoxPR_curve.png` — Precision-Recall curve
- `BoxF1_curve.png` — F1-Confidence curve
- `confusion_matrix_normalized.png` — Normalized confusion matrix
- `results.csv` — Per-epoch training metrics
- `val_batch0_pred.jpg` — Visual prediction sample

These are already generated in `runs/detect/train/` for Phase 1.

---

## ROI Integration

After model evaluation:
1. Load `best.pt` in Flask backend
2. Run inference on camera frame
3. Check if any `child` class bbox centroid falls inside the Crosswalk ROI polygon
4. If YES → `warning_device_on = True`, `child_in_roi = True`
5. Emit `status_update` via Socket.IO
6. Log event to MySQL (only on state change)

---

## Edge Deployment Notes

- Target device: Raspberry Pi or Jetson Nano (IoT edge)
- Use TFLite or ONNX export if Pi deployment
- Keep model as `yolov8n` (nano) for latency constraint
- Latency must be measured end-to-end (capture → detection → emit → log)
