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
└── 04_raw_frames_backup/          # Re-extracted raw frames (Label Studio reference)
    └── afternoon_v2_frames/       #   908 frames from Afternoon V2 videos
```

## Latest Model

- **File:** `03_training_runs/run_2026_04_03_merged_v2/weights/yolov8n_crosswalk_v2_1111_frames.pt`
- **mAP50:** 96.75%
- **mAP50-95:** 74.20%
- **Precision:** 96.73%
- **Recall:** 89.79%
- **F1 Score:** 0.91
- **Dataset:** 1,111 frames (Morning V1 + Afternoon V1 + Afternoon V2)
- **Classes:** adult (0), child (1)
