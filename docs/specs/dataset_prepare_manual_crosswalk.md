# Directive: Manual Crosswalk Dataset Preparation

## Goal

Prepare the team-collected crosswalk dataset for labeling, validation, and export without mixing in legacy external datasets.

## Scope

- In scope:
  - site video ingestion
  - frame extraction and review
  - YOLO label creation
  - label validation
  - train/val/test export generation
- Out of scope:
  - external dataset import
  - reuse of removed legacy training data
  - model training before the manual dataset is validated

## Inputs Required

- `datasets/site_dataset_v1/videos_raw/`
- `datasets/site_dataset_v1/frames_raw/`
- `datasets/site_dataset_v1/frames_selected/`
- `datasets/site_dataset_v1/labels/`

## Tools / Scripts

1. `scripts/setup_datasets.py`
2. `scripts/validate_labels.py`
3. `scripts/split_dataset.py`

## Outputs / Deliverables

- curated selected frames under `datasets/site_dataset_v1/frames_selected/`
- YOLO labels under `datasets/site_dataset_v1/labels/`
- exported training dataset under `datasets/site_dataset_v1/exports/yolo/`
- `datasets/site_dataset_v1/exports/yolo/data.yaml`
- validation report in `reports/site_dataset_v1_label_validation.csv`

## Steps

1. Run `python scripts/setup_datasets.py` to scaffold or refresh the manual dataset workspace.
2. Save raw crosswalk recordings in `videos_raw/`.
3. Extract frames into `frames_raw/`.
4. Move only approved, non-duplicate frames into `frames_selected/`.
5. Create YOLO labels in `labels/` with the same relative filenames as the selected frames.
6. Run `python scripts/validate_labels.py --dataset site_dataset_v1`.
7. Fix or remove any frames that fail validation.
8. Run `python scripts/split_dataset.py --dataset site_dataset_v1`.
9. Confirm `datasets/site_dataset_v1/exports/yolo/data.yaml` points at the generated export root.

## Edge Cases

- image exists but label is missing -> validation must fail
- label exists but frame was rejected -> remove or relocate the orphan label
- duplicate near-identical frames -> keep only one in `frames_selected/`, move the rest to `rejected/`
- motion blur, heavy occlusion, or unusable nighttime glare -> move to `rejected/`

## Validation

- `frames_selected/` and `labels/` contain paired files only
- all YOLO coordinates remain within `[0, 1]`
- exported `train`, `val`, and `test` folders are created under `exports/yolo/`
- no legacy dataset folder is referenced anywhere in the export config
