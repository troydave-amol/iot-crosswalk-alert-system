---
name: smart-crosswalk
description: |
  Full-stack AI agent skill for the IoT-Based Smart School-Zone Crosswalk Alert System capstone.
  Use this skill for dashboard/backend work, ROI logic, event analytics, dataset and training review,
  and repo-state analysis. Treat current inconsistencies such as class-index drift, ROI API drift,
  and legacy helper scripts as first-class concerns rather than hidden footnotes.
---

# Smart Crosswalk Capstone Skill

## Project Identity

**Title**: IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection  
**Stack**: YOLO + Flask + Socket.IO + MySQL + HTML/CSS/JS dashboard

## Current Repo Ground Truth

- live camera mode and video-test mode both exist in the dashboard
- a trained checkpoint already exists at `models/yolov8n_crosswalk_v2_1111_frames.pt`
- current archived datasets and training runs live under `datasets/`
- the dashboard persists ROI as a rectangle in `roi_config.json`
- analytics and reports are backed by server-side APIs, not just client-side calculations

## Must-Track Inconsistencies

### Class mapping

- runtime currently behaves as though class `1` is the child trigger class
- scaffold/export scripts still emit `0: child_like`, `1: adult_like`
- `datasets/02_yolo_dataset/data.yaml` uses `['adult', 'child']`

### ROI API drift

- `cv_inference.ROI` is polygon-first
- older tests and helper scripts still call the older rectangle constructor patterns

### Script staleness

Do not assume every helper in `scripts/` is current. Some still reference older dataset names or older API/table fields.

## Recommended Workflow

### Runtime or analytics work

Read:

- `docs/specs/api_events_contract.md`
- `docs/specs/api_analytics_aggregates.md`
- `docs/specs/roi_logic_and_trigger_rules.md`

Inspect:

- `app.py`
- `db.py`
- `cv_inference.py`
- `warning_controller.py`
- `detection_tracker.py`

### Dataset or training work

Read:

- `docs/specs/dataset_prepare_manual_crosswalk.md`
- `docs/specs/annotation_guideline_child_class.md`
- `docs/specs/yolov8_training_plan.md`

Inspect:

- `datasets/`
- `models/`
- `training/`
- selected scripts in `scripts/`

## Validation Notes

Known good during the latest repo audit:

- py_compile on the core Python modules
- `scripts/validate_labels.py --help`
- `scripts/split_dataset.py --help`

Known stale or failing:

- `test_detection_stabilization.py`
- `scripts/offline_validation.py`
- `scripts/test_infer_video.py`
- `scripts/verify_db.py`

## Operating Principles

- preserve visual-warning-only scope
- do not make biological age claims
- surface inconsistencies instead of documenting around them
- prefer current code behavior over older Markdown assumptions
