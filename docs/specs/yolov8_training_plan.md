# YOLOv8 Training Plan

## Current Training State

The repo already contains an existing training lineage and a copied checkpoint:

- checkpoint in `models/yolov8n_crosswalk_v2_1111_frames.pt`
- archived run in `datasets/03_training_runs/run_2026_04_03_merged_v2/`
- merged dataset snapshot in `datasets/02_yolo_dataset/`

Latest archived run metrics from `results.csv`:

| Metric | Value |
|---|---|
| Precision | `0.96731` |
| Recall | `0.89794` |
| mAP50 | `0.96745` |
| mAP50-95 | `0.74197` |

## Pre-Training Checks

Before starting any new run:

1. inspect the dataset `data.yaml`
2. confirm class order matches the runtime expectation you plan to deploy
3. confirm `train`, `val`, and `test` paths are correct
4. confirm the chosen dataset is the intended source of truth, not just an older archived artifact

## Important Repo Caveats

### Class mapping is not fully normalized

- archived merged dataset behavior currently aligns with `adult=0`, `child=1`
- scaffold/export scripts still emit `child_like=0`, `adult_like=1`
- runtime inference currently behaves as though class `1` is the child trigger class

Do not train and deploy across those boundaries without reconciling the class map first.

### Dataset YAMLs should be reviewed manually

`datasets/02_yolo_dataset/data.yaml` currently contains:

- `train: images/train`
- `val: images/train`

Treat dataset YAMLs as reviewable configuration, not unquestioned truth.

## Suggested Training Inputs

If continuing the current merged dataset line:

- dataset config: `datasets/02_yolo_dataset/data.yaml`
- output root: prefer a dated subfolder under `datasets/03_training_runs/` or `runs/`

If starting a fresh manual dataset line:

1. scaffold with `scripts/setup_datasets.py`
2. validate with `scripts/validate_labels.py`
3. export with `scripts/split_dataset.py`
4. inspect the exported YAML and class map before training

## Suggested Training Command Template

```powershell
yolo detect train `
  model=yolov8n.pt `
  data=datasets/02_yolo_dataset/data.yaml `
  epochs=100 `
  imgsz=640 `
  batch=8 `
  project=datasets/03_training_runs `
  name=run_YYYY_MM_DD
```

Adjust the dataset path only after verifying the class order and split paths.

## Deployment Handoff

After a new model is approved:

1. place or copy the checkpoint into `models/`
2. point `MODEL_PATH` at that file
3. verify live inference, ROI gating, warning behavior, and analytics logging against the new model

## Output Artifacts To Keep

- `results.csv`
- training curve images
- confusion matrices
- representative validation predictions
- the exact `args.yaml` for the run
- a note describing the dataset class order used for that run
