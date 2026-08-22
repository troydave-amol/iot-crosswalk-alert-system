# Directive: Dataset Preparation And Export Workflow

## Goal

Document the dataset workflow that actually exists in the repo today:

- archived merged training assets already live under `datasets/`
- manual scaffold scripts still exist for building a fresh site-specific dataset

This document covers both, and it calls out the places where they currently disagree.

## Current Dataset Baseline

The repository already contains:

- `datasets/01_label_studio_exports/`
  - zipped annotation exports
- `datasets/02_yolo_dataset/`
  - merged YOLO dataset snapshot
- `datasets/03_training_runs/`
  - archived YOLO run artifacts
- `datasets/04_raw_frames_backup/`
  - raw frame backups
- `datasets/August 11, 2026 Frames/`
  - active dataset: 5,650 frames from Morning, Afternoon 12 PM, and Afternoon 2 PM videos, consolidated into 57 batch folders (`batch_001` to `batch_057`) of 100 frames each for Label Studio annotation

Separately, `scripts/setup_datasets.py` can still scaffold a fresh manual workspace such as `datasets/site_dataset_v1/`.

## Supported Workflow A: Maintain The Current Merged Dataset Lineage

Use this when reviewing or extending the dataset that produced the current checkpoint lineage.

Inputs:

- archived exports in `datasets/01_label_studio_exports/`
- current training dataset in `datasets/02_yolo_dataset/`
- archived run outputs in `datasets/03_training_runs/`

Checks:

1. open the target dataset `data.yaml`
2. verify class order before training or deployment
3. verify `train`, `val`, and `test` paths are correct for the dataset snapshot being used
4. keep any new exports and training artifacts traceable to their source labels

## Supported Workflow B: Build A Fresh Manual Dataset Workspace

Use this when starting a new site-specific collection and labeling cycle.

### Scaffold

```powershell
python scripts/setup_datasets.py
```

This creates the workspace shape under `datasets/site_dataset_v1/`:

- `videos_raw/`
- `raw_frames/`
- `selected_frames/`
- `labels/`
- `annotation_exports/`
- `rejected/`

### Validate Labels

```powershell
python scripts/validate_labels.py --dataset site_dataset_v1
```

### Export Train/Val/Test

```powershell
python scripts/split_dataset.py --dataset site_dataset_v1
```

## Mandatory Reconciliation Step

Before using any newly exported manual dataset with the current runtime:

1. inspect the exported `data.yaml`
2. compare its class order with the runtime expectation in `app.py` and `cv_inference.py`
3. resolve any mismatch before training or deploying

Reason:

- current scaffold scripts still emit `0: child_like`, `1: adult_like`
- current runtime logic behaves as though class `1` is the child trigger class
- the archived merged dataset snapshot uses `['adult', 'child']`

## Outputs

For a fresh manual workspace, the expected outputs are:

- curated images under `selected_frames/`
- YOLO labels under `labels/`
- validation report in `reports/<dataset>_label_validation.csv`
- exported split under `annotation_exports/yolo/`

## Validation Rules

- every selected image should have a paired label file
- label rows must stay within normalized YOLO bounds
- split generation should create `images/train|val|test` and `labels/train|val|test`
- dataset metadata must be reviewed, not assumed

## Current Caveats

- `datasets/02_yolo_dataset/data.yaml` currently points `val` to `images/train`, so treat dataset YAMLs as reviewable artifacts rather than trusted truth
- older scripts elsewhere in the repo still reference historical dataset names and should not be treated as the active export path by default
