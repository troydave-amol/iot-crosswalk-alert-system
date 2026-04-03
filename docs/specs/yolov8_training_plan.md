# YOLOv8 Training Plan

## Current Status

As of March 20, 2026, there is no approved active detector in the repository. Training must restart from the manually gathered site dataset only.

## Dataset

Active export:

- `datasets/site_dataset_v1/annotation_exports/yolo/data.yaml`

Expected classes:

- `0: child_like`
- `1: adult_like`

## Training Preconditions

Do not start training until all of these are true:

1. `selected_frames/` has enough varied site footage
2. labels pass `scripts/validate_labels.py`
3. `annotation_exports/yolo/` has a clean train/val/test split
4. the manuscript language matches the annotation guideline

## Baseline Training Configuration

Use a fresh YOLOv8 nano checkpoint downloaded at training time, not an old repo-carried weight file.

```yaml
model: yolov8n.pt
data: datasets/site_dataset_v1/annotation_exports/yolo/data.yaml
epochs: 50
imgsz: 640
batch: 16
workers: 2
device: 0
project: runs
name: manual_site_v1
```

## Output Targets

- best model copied to `models/manual_crosswalk_detector.pt`
- full run artifacts stored in `runs/manual_site_v1/`
- evaluation summary saved under `reports/`

## Runtime Integration

After a new model is approved:

1. place it at `models/manual_crosswalk_detector.pt` or set `MODEL_PATH`
2. run the live app
3. confirm ROI-trigger behavior on real or recorded site footage
4. verify DB events and analytics still match the emitted live state

## Evaluation Targets

| Metric | Target |
|---|---|
| Precision | >= 0.80 |
| Recall | >= 0.75 |
| mAP@0.5 | >= 0.80 |
| Inference latency | <= 100 ms/frame |

## Required Evaluation Artifacts

- `results.csv`
- `BoxPR_curve.png`
- `BoxF1_curve.png`
- `confusion_matrix_normalized.png`
- representative validation predictions

## Deployment Notes

- keep the live warning logic child-only inside ROI
- keep anti-flicker stabilization enabled
- measure end-to-end latency from capture to dashboard update
- do not claim biological age estimation in any report or demo
