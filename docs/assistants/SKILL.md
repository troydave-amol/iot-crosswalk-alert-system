---
name: smart-crosswalk
description: |
  Full-stack AI agent skill for the IoT-Based Smart School-Zone Crosswalk Alert System capstone project.
  Use this skill for manual dataset preparation, YOLOv8 training from site-collected data,
  Flask+MySQL backend work, Socket.IO dashboard updates, analytics validation, ROI trigger logic,
  and report generation. Enforces project scope: visual warning only, no SMS/audio/age estimation/face recognition.
---

# Smart Crosswalk Capstone

## Project Identity

**Title**: IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection
**Client**: Traffic Management Center (TMC), Casisang Central School crosswalk, Barangay Casisang, Malaybalay City
**Stack**: YOLOv8 + Flask + MySQL + Socket.IO + HTML/JS dashboard

## Non-Negotiable Scope Rules

- Detection wording must remain: visually classified as children based on body size, proportions, and school-age appearance
- Warning output must remain visual only
- No SMS, no audio, no face recognition, no biological age claims
- Warning turns ON only when a child-classified pedestrian is inside the Crosswalk ROI

## Active Dataset Policy

The active workflow is manual-dataset-only.

- Working dataset root: `datasets/site_dataset_v1/`
- Ignore removed legacy datasets and prior training artifacts in active decisions
- Do not rely on an old detector as a valid deliverable

## Workflow Decision Tree

- Dataset / annotations -> follow Dataset Workflow
- Model training / evaluation -> follow Training Workflow
- Backend / API -> follow Backend Workflow
- Dashboard / frontend -> follow Frontend Workflow
- Analytics correctness -> follow Analytics Validation Workflow

## Dataset Workflow

1. Confirm `datasets/site_dataset_v1/` structure exists
2. Use `selected_frames/` + `labels/` as the labeling source of truth
3. Validate labels with `scripts/validate_labels.py --dataset site_dataset_v1`
4. Export train/val/test via `scripts/split_dataset.py --dataset site_dataset_v1`
5. Use `docs/specs/annotation_guideline_child_class.md` for class rules

## Training Workflow

1. Train only from `datasets/site_dataset_v1/annotation_exports/yolo/data.yaml`
2. Save approved best weights to `models/manual_crosswalk_detector.pt`
3. Save training artifacts under `runs/`
4. Record evaluation metrics for the manuscript
5. See `docs/specs/yolov8_training_plan.md`

## Backend Workflow

Flask app: `app.py`
DB layer: `db.py`

Critical requirements:

- `/api/events` must keep correct range filtering and pagination
- `/api/analytics` must stay SQL-accurate
- missing model must not crash live view; system should fail safe with warning OFF

## Frontend Workflow

Entry: `templates/index.html`
Assets: `static/`

Keep these rules:

- 15m subset 1h subset today subset all
- dashboard numbers must match backend API
- live payloads must remain contract-valid even when detection is idle

## Analytics Validation Workflow

1. compute SQL truth
2. compare against `/api/analytics`
3. compare against dashboard KPIs
4. treat mismatches as bugs until proven otherwise

## Resources

- `docs/specs/dataset_prepare_manual_crosswalk.md`
- `docs/specs/annotation_guideline_child_class.md`
- `docs/specs/yolov8_training_plan.md`
- `docs/specs/api_events_contract.md`
- `docs/specs/api_analytics_aggregates.md`
- `docs/specs/roi_logic_and_trigger_rules.md`
- `scripts/`
