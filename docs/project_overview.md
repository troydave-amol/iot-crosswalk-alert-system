# Smart Crosswalk Capstone Overview

## Current Project State

On March 20, 2026, the project direction was reset. The active repository now supports only a manual dataset collection workflow for the school-zone crosswalk deployment site.

This means:

- old external datasets are not part of the active pipeline
- the previous trained detector is not considered valid for deployment or reporting
- the app must remain stable even when no trained model file is present

## What the System Still Does

The dashboard and backend remain the same core system:

- `app.py`
  - Flask + Socket.IO server for live view, logs, analytics, reports, and ROI APIs
- `cv_inference.py`
  - YOLO inference wrapper used once a new manual model is available
- `warning_controller.py`
  - temporal stabilization plus warning hold/cooldown logic
- `db.py`
  - MySQL initialization, event inserts, event retrieval, and analytics aggregates

## Active Folder Structure

The repo now treats this layout as the source of truth:

- `datasets/site_dataset_v1/videos_raw/`
  - original camera recordings from the deployment site
- `datasets/site_dataset_v1/frames_raw/`
  - extracted frames before review
- `datasets/site_dataset_v1/frames_selected/`
  - approved frames to annotate
- `datasets/site_dataset_v1/labels/`
  - YOLO labels matching `frames_selected/`
- `datasets/site_dataset_v1/exports/`
  - generated train/val/test exports
- `datasets/site_dataset_v1/rejected/`
  - blurred, duplicated, or unusable frames
- `models/`
  - destination for the next approved manual-model weights
- `training/`
  - notes, experiments, and reproducible training commands
- `runs/`
  - future training/evaluation outputs

## Runtime Safety Behavior

The live system now fails safe when the model file is missing:

- camera feed still opens
- ROI overlay still works
- dashboard receives valid `idle` status payloads
- `child_in_roi = false`
- `warning_device_on = false`

This avoids a crash while the team is still collecting and labeling the new dataset.

## Manual Dataset Workflow

1. Record site footage and store it in `videos_raw/`.
2. Extract candidate frames into `frames_raw/`.
3. Move only usable frames into `frames_selected/`.
4. Create YOLO labels in `labels/`.
5. Validate labels with `scripts/validate_labels.py`.
6. Export a clean split with `scripts/split_dataset.py`.
7. Train a new detector only from the exported manual dataset.

## Scripts That Remain Relevant

- `scripts/setup_datasets.py`
  - creates the manual dataset scaffold
- `scripts/validate_labels.py`
  - checks missing labels, malformed rows, and out-of-bounds values
- `scripts/split_dataset.py`
  - copies `frames_selected/` + `labels/` into `exports/yolo/images|labels/train|val|test`
- `scripts/test_infer_video.py`
  - sanity-checks a future manual model on a local validation video
- `scripts/smoke_test_api.py`
  - confirms API availability and response shape
- `scripts/verify_db.py`
  - compares SQL truth against backend analytics responses

## Immediate Next Steps

- collect more site footage
- define the exact annotation protocol for child-like and adult-like pedestrians
- validate label quality before any new training run
- retrain only after the manual export is large enough for a meaningful split
