# Agent Instructions - Smart Crosswalk Capstone

> Mirror this file across `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` so the same instructions load in any AI environment.

You are supporting a capstone project that combines:

- YOLO-based pedestrian classification
- Hikvision RTSP live streaming
- Flask + Socket.IO dashboard delivery
- MySQL event logging and analytics
- ROI-gated visual warning logic

## Current Repo Reality

Treat these as the current ground truth for this repository:

- the repo already contains a trained checkpoint at `models/yolov8n_crosswalk_v2_1111_frames.pt`
- the dashboard supports both live camera mode and video-test mode
- the current merged dataset and archived training assets live under `datasets/`
- the checked-in ROI config is rectangular, even though the lower-level ROI helper is polygon-capable
- logs and analytics are server-side and DB-backed, not browser-only summaries

## High-Priority Inconsistencies

Surface these rather than glossing over them:

### 1. Class-index mismatch

- runtime inference currently behaves as though class `1` is the child class
- scaffold/export scripts still emit `0: child_like`, `1: adult_like`
- `datasets/02_yolo_dataset/data.yaml` uses `['adult', 'child']`

Any work touching training, deployment, labels, or evaluation must explicitly account for that mismatch.

### 2. ROI API drift

- `cv_inference.ROI` is now polygon-first
- older tests and scripts still call rectangle-style constructors directly
- ROI-related failures in tests are currently expected until that API is normalized

### 3. Legacy helper scripts

Some scripts still point to older datasets such as `merged_v2`, `merged_dataset_v1`, or `afternoon_v1`. Do not assume every script in `scripts/` is current just because it exists.

## Core Behavior To Preserve

- warning output must remain visual only
- no biological age claims
- no face recognition
- no plate recognition
- warning ON only when the child trigger condition is satisfied inside the ROI after stabilization
- DB failures must not crash the app

## Recommended Working Order

### Runtime and backend work

Read first:

- `docs/specs/api_events_contract.md`
- `docs/specs/api_analytics_aggregates.md`
- `docs/specs/roi_logic_and_trigger_rules.md`

Then inspect:

- `app.py`
- `db.py`
- `cv_inference.py`
- `warning_controller.py`
- `detection_tracker.py`

### Dataset and training work

Read first:

- `docs/specs/dataset_prepare_manual_crosswalk.md`
- `docs/specs/annotation_guideline_child_class.md`
- `docs/specs/yolov8_training_plan.md`

Then inspect:

- `datasets/`
- `models/`
- `training/`
- relevant scripts under `scripts/`

## Validation Guidance

Currently verified during docs refresh:

- py_compile for the core Python modules passes
- `test_detection_stabilization.py` fails because of ROI API drift
- `test_backend.py` expects a running server and is not a pure unit test
- `scripts/offline_validation.py` is stale against the current ROI API
- `scripts/test_infer_video.py` has import-path issues when run directly from `scripts/`

Prefer validating current behavior from code and targeted commands rather than assuming all helper scripts are trustworthy.

## Summary

Be precise about what is implemented, what is archived, and what is currently inconsistent. Future contributors should be able to read your output and immediately tell which parts of the repo are production-path, which are historical, and which need reconciliation before the next training or deployment cycle.
