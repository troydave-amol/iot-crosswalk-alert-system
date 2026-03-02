# YOLOv8 Training Plan

## Model
- Base: `yolov8n.pt` (nano, edge-friendly)
- Framework: Ultralytics YOLOv8
- Task: object detection (`child_like`, `adult_like`)

## Phase 1: Baseline Person Detection
Train on CityPersons + JAAD to establish pedestrian detection baseline.

```yaml
model: yolov8n.pt
data: datasets/citypersons.yaml
epochs: 50
imgsz: 640
batch: 16
workers: 2
device: 0
```

Output: `runs/detect/train/weights/best.pt`

## Phase 2: Child-Class Fine-Tuning
Fine-tune baseline on child-labeled dataset.

```yaml
model: runs/detect/train/weights/best.pt
data: datasets/crosswalk_child.yaml
epochs: 30
imgsz: 640
batch: 16
freeze: 10
```

## Phase 2b: Mapping Fix + Retrain (`young` -> `child_like`)
The JAAD exporter mapping was corrected so `child` and `young` map to `child_like`, while older groups map to `adult_like`.

Automation script: `scripts/retrain_childlike_v2.py`
1. Clear old export and split
2. Re-export JAAD with corrected mapping
3. Re-split dataset
4. Fine-tune from current best model
5. Copy new `best.pt` into `models/`

## Runtime Inference and Trigger Notes
- Runtime trigger logic is child-only. `adult_like` fallback is disabled for warning decisions.
- Runtime uses:
  - `agnostic_nms=True`
  - IoU threshold around `0.60`
  - confidence gate (`LIVE_CHILD_CONF`)
  - minimum bbox-height ratio gate (`LIVE_MIN_CHILD_BBOX_RATIO`, default `0.18`)
  - ROI bottom-center inclusion check
- Raw detector decisions are stabilized with a 3-of-5 temporal vote before setting canonical `child_in_roi`.

## Evaluation Targets (Manuscript)
| Metric | Target |
|---|---|
| Precision | >= 0.80 |
| Recall | >= 0.75 |
| mAP@0.5 | >= 0.80 |
| Inference latency | <= 100 ms/frame |

## Required Evaluation Artifacts
- `BoxPR_curve.png`
- `BoxF1_curve.png`
- `confusion_matrix_normalized.png`
- `results.csv`
- `val_batch0_pred.jpg`

## ROI Integration
After model evaluation:
1. Load `best.pt` in Flask backend
2. Run inference on camera frame
3. Build raw trigger candidates with confidence, min-size, and ROI checks
4. Stabilize to canonical `child_in_roi`
5. Set `warning_device_on` from canonical signal + hold/cooldown
6. Emit `status_update` and log events to MySQL

## Edge Deployment Notes
- Target: Raspberry Pi or Jetson Nano
- Export to ONNX/TFLite if needed
- Keep `yolov8n` for latency budget
- Measure end-to-end latency (capture -> detect -> emit -> log)
