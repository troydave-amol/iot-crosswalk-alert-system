# Datasets Directory

Organized structure for the Crosswalk Pedestrian Detection project.

## Folder Structure

```
datasets/
├── 01_label_studio_exports/       # Label Studio YOLO-format ZIP exports
│   ├── Afternoon_V1.zip           #   250 labeled frames
│   ├── Afternoon_V2.zip           #   869 labeled frames
│   └── Morning_V1.zip             #   ~200 labeled frames
│
├── 02_yolo_dataset/               # Final merged training dataset
│   ├── images/train/              #   1,111 JPG images
│   ├── labels/train/              #   1,111 TXT label files (YOLO format)
│   ├── data.yaml                  #   YOLO training config
│   └── classes.txt                #   Class names: adult (0), child (1)
│
├── 03_training_runs/              # YOLOv8 training output
│   └── run_2026_04_03_merged_v2/  #   Latest run (100 epochs, 1,111 images)
│       ├── weights/
│       │   └── yolov8n_crosswalk_v2_1111_frames.pt    # Best checkpoint
│       ├── results.csv            #   Epoch-by-epoch metrics
│       ├── results.png            #   Training curves
│       ├── confusion_matrix*.png  #   Confusion matrices
│       ├── Box*_curve.png         #   F1, PR, P, R curves
│       └── *.jpg                  #   Train/val batch previews
│
├── 04_raw_frames_backup/          # Re-extracted raw frames (Label Studio reference)
│   └── afternoon_v2_frames/       #   908 frames from Afternoon V2 videos
│
└── August 11, 2026 Frames/        # Active dataset for Label Studio annotation
    └── batch_001/ ... batch_057/  #   5,650 frames split into 57 batches (100 frames each)
```

## Active Annotation Dataset (August 11, 2026)

- **Source Videos:** Morning (6 clips), Afternoon 12 PM (4 clips), Afternoon 2 PM (12 clips) — 22 clips total.
- **Extraction Rate:** 1 FPS frame extraction.
- **Consolidation:** 5,650 total frames consolidated into a single sequence (`frame_00001.jpg` to `frame_05650.jpg`).
- **Batching:** Grouped into 57 batch folders (`batch_001` through `batch_057`) of 100 frames each (batch 57 has 50 frames) for Label Studio import.
- **Batching Script:** `scripts/batch_for_labelstudio.py`

## Latest Trained Model Checkpoint

- **File:** `03_training_runs/run_2026_04_03_merged_v2/weights/yolov8n_crosswalk_v2_1111_frames.pt`
- **mAP50:** 96.75%
- **mAP50-95:** 74.20%
- **Precision:** 96.73%
- **Recall:** 89.79%
- **F1 Score:** 0.91
- **Dataset:** 1,111 frames (Morning V1 + Afternoon V1 + Afternoon V2)
- **Classes:** adult (0), child (1)

