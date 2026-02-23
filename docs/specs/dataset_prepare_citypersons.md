# Directive: Dataset Preparation — CityPersons

## Goal
Convert the CityPersons dataset into YOLO format and validate it for use as the pedestrian baseline model training data.

## Scope
- **In scope**: Image listing, annotation conversion, label validation, train/val/test split
- **Out of scope**: Re-labeling child vs. adult class (handled by `annotation_guideline_child_class.md`)

## Inputs Required
- `datasets/citypersons/images/` — raw images
- `datasets/citypersons/labels/` — YOLO `.txt` labels (one per image)
- `datasets/citypersons.yaml` — dataset config

## Tools / Scripts
1. `scripts/validate_labels.py` — check label bounds, missing labels, empty files
2. `scripts/split_dataset.py`   — create `train/val/test` sub-splits (80/10/10 default)
3. `scripts/setup_datasets.py`  — verify final data.yaml and path resolution

## Outputs / Deliverables
- `datasets/citypersons/images/train/`, `val/`, `test/`
- `datasets/citypersons/labels/train/`, `val/`, `test/`
- Validated `datasets/citypersons.yaml` with correct `train:`, `val:`, `test:` paths
- Label validation report saved to `reports/citypersons_label_validation.csv`

## Steps
1. Run `python scripts/validate_labels.py --dataset citypersons` and review output.
2. Fix any out-of-bounds or missing labels flagged by the validator.
3. Run `python scripts/split_dataset.py --dataset citypersons --split 80 10 10`.
4. Update `datasets/citypersons.yaml` train/val/test paths to point to sub-splits.
5. Run `python scripts/setup_datasets.py --dataset citypersons` to verify.

## Edge Cases
- Images without a corresponding label file → validator must flag and log, not crash.
- Labels with coordinates outside [0, 1] → clamp and log, or skip image.
- Duplicate filenames across train/val/test → must not occur; split script must deduplicate.

## Validation
- All 3 sub-splits must be non-empty.
- `citypersons.yaml` `nc` must be 1 (person class only at baseline).
- No label file should have class IDs other than 0.
