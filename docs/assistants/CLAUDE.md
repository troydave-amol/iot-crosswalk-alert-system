# Agent Instructions - Smart Crosswalk Capstone

> Mirror this file across `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` so the same instructions load in any AI environment.

You are supporting a capstone project that combines:

- Computer Vision (YOLOv8)
- Edge/IoT deployment
- Flask + MySQL backend
- Web dashboard (Live View, Logs, Analytics, Reports, Settings)

## Project Context

**Official Title**
IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection

**Client / Location**

- Client: Traffic Management Center (TMC)
- Location: Casisang Central School crosswalk, Barangay Casisang, Malaybalay City

**Core Behavior**

- Detect pedestrians visually classified as children based on body size, proportions, and school-age appearance.
- Do not claim biological age estimation.
- Warning ON only when a child-classified pedestrian is inside the Crosswalk ROI.
- Warning OFF otherwise.
- Visual warning only. No SMS. No sirens. No face recognition.
- Store events in MySQL and keep dashboard analytics range-accurate.

## Active Dataset Policy

The active repository workflow is manual-dataset-only.

- Use `datasets/site_dataset_v1/` as the working dataset root.
- Do not reintroduce removed legacy external datasets into the active pipeline.
- Do not treat prior trained model artifacts as approved deliverables.

## 3-Layer Architecture

### Layer 1: Directive

- SOPs live in `docs/specs/`
- Each directive should define goal, scope, inputs, tools, outputs, edge cases, and validation

Relevant directives:

- `docs/specs/dataset_prepare_manual_crosswalk.md`
- `docs/specs/annotation_guideline_child_class.md`
- `docs/specs/yolov8_training_plan.md`
- `docs/specs/api_events_contract.md`
- `docs/specs/api_analytics_aggregates.md`
- `docs/specs/roi_logic_and_trigger_rules.md`

### Layer 2: Orchestration

- Read the relevant directive
- Prefer deterministic scripts over manual steps
- Keep scope aligned with the capstone rules
- Ask only the minimum clarifying questions required

### Layer 3: Execution

- Scripts live in `scripts/`
- Scripts should be fast, repeatable, and parameter-driven
- Use validation scripts for labels, exports, API checks, and DB checks

## Operating Principles

### 1) Scope protection first

- visual warning only
- no SMS/audio
- no biological age claims
- no face or plate recognition

### 2) Check for tools first

Before creating new scripts, inspect `scripts/` for an existing fit.

### 3) Determinism for critical logic

Time ranges, analytics aggregates, ROI trigger rules, and API contracts must be validated with deterministic code and reproducible checks.

### 4) Fail safe

If the live model file is missing, keep the app stable and warning output OFF instead of crashing.

### 5) Validate with ground truth

For analytics correctness:

- SQL truth must match API response
- API response must match dashboard values for the same range

## Directory Guidance

- `.tmp/` - temporary files
- `docs/specs/` - SOPs
- `scripts/` - deterministic tools
- `datasets/site_dataset_v1/` - manual dataset workspace
- `models/` - approved trained weights only
- `training/` - reproducible training notes and commands
- `reports/` - summaries and evaluations

## Typical Directives

### Dataset preparation

- record footage
- extract frames
- review and select usable frames
- annotate YOLO labels
- validate labels
- export train/val/test

### Training and evaluation

- train only from the manual site export
- evaluate precision, recall, F1, and latency
- document results for the manuscript

### Integration

- feed YOLO detections into ROI logic
- emit `status_update`
- log meaningful events into MySQL
- verify analytics matches SQL

## Summary

Be pragmatic. Be reliable. Keep the repo aligned with the manual dataset reset.
