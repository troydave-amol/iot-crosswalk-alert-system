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

## Phase 2b: Mapping Fix + Retrain (young → child_like)

The original exporter treated JAAD `young` (age_scalar=1) as `adult_like`, causing misclassification of school-age children. Fixed by mapping both `child` and `young` → `child_like`.

**What changed:**
- `export_jaad_childlike_yolo.py`: `map_age_to_class()` now maps `(0, 1) → child_like`, `(2, 3) → adult_like`
- `cv_inference.py`: Added size-based fallback — `adult_like` detections with bbox ≤ 35% frame height also trigger warning

**Automation script:** `scripts/retrain_childlike_v2.py`
1. Clears old export + split
2. Re-exports JAAD with corrected mapping
3. Resplits dataset
4. Fine-tunes 30 epochs from current best (`models/yolov8_childlike_best.pt`)
5. Copies new `best.pt` back to `models/`

```bash
python scripts/retrain_childlike_v2.py
```

Config: `epochs=30`, `batch=8`, `freeze=10`, `patience=15`

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
