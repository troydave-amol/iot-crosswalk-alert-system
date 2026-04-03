import os
import shutil
import random
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
RAW_FRAMES_DIR = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "raw_frames"
EXTRACTED_LABELS_DIR = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "annotation_exports" / "extracted_labels"
OUTPUT_DATASET_DIR = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "yolo_dataset"

VAL_SPLIT_RATIO = 0.2
RANDOM_SEED = 42

CLASSES = ["adult", "child"]
# ───────────────────────────────────────────────────────────────

def build_yolo_dataset():
    if not EXTRACTED_LABELS_DIR.exists():
        print(f"[ERROR] Extracted labels not found at {EXTRACTED_LABELS_DIR}")
        return

    # Clear and recreate output directory structure
    if OUTPUT_DATASET_DIR.exists():
        shutil.rmtree(OUTPUT_DATASET_DIR)
        
    for split in ["train", "val"]:
        (OUTPUT_DATASET_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DATASET_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    # 1. Collect all raw images
    all_images = list(RAW_FRAMES_DIR.rglob("*.jpg"))
    print(f"Found {len(all_images)} raw images.")

    # 2. Collect all labels and map them by their real filename (strip the hash prefix)
    all_labels = list(EXTRACTED_LABELS_DIR.glob("*.txt"))
    label_map = {}
    for label_path in all_labels:
        # Label Studio uses formatting: hash__filename.ext.txt or just hash__filename.txt
        # E.g., 010b8cc4__AftV2_video_00049.txt
        parts = label_path.name.split("__", 1)
        if len(parts) == 2:
            real_stem = parts[1].replace(".txt", "")
            if real_stem.endswith(".jpg"):
                real_stem = real_stem[:-4]
            label_map[real_stem] = label_path
        else:
            # Fallback if no double underscore
            label_map[label_path.stem] = label_path
            
    print(f"Found {len(all_labels)} label files.")

    # 3. Match images with their labels filter and split
    matched_data = []
    missing_labels = 0

    for img_path in all_images:
        stem = img_path.stem
        if stem in label_map:
            # Check if label file is empty (meaning no persons)
            label_file = label_map[stem]
            if os.path.getsize(label_file) == 0:
                print(f"Skipping empty label (no persons): {stem}")
                continue
                
            matched_data.append((img_path, label_file))
        else:
            missing_labels += 1
            
    print(f"Successfully matched {len(matched_data)} annotated images.")
    if missing_labels > 0:
        print(f"Warning: {missing_labels} images had no corresponding label file.")

    # Shuffle and Split
    random.seed(RANDOM_SEED)
    random.shuffle(matched_data)
    
    val_count = int(len(matched_data) * VAL_SPLIT_RATIO)
    train_data = matched_data[val_count:]
    val_data = matched_data[:val_count]

    # 4. Copy files to train/val dirs
    def copy_split(data_list, split_name):
        img_dir = OUTPUT_DATASET_DIR / split_name / "images"
        lbl_dir = OUTPUT_DATASET_DIR / split_name / "labels"
        for img_p, lbl_p in data_list:
            shutil.copy(str(img_p), str(img_dir / img_p.name))
            
            # Destination label must exactly match image name stem + .txt
            dest_lbl_name = f"{img_p.stem}.txt"
            shutil.copy(str(lbl_p), str(lbl_dir / dest_lbl_name))

    print("Copying Training data...")
    copy_split(train_data, "train")
    
    print("Copying Validation data...")
    copy_split(val_data, "val")

    # 5. Generate dataset.yaml
    yaml_path = OUTPUT_DATASET_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {OUTPUT_DATASET_DIR.absolute()}\n")
        f.write("train: train/images\n")
        f.write("val: val/images\n\n")
        f.write("names:\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"  {i}: {class_name}\n")

    print(f"\n{'='*50}")
    print(f"Dataset preparation complete!")
    print(f"Total valid labeled frames: {len(matched_data)}")
    print(f"Train split: {len(train_data)}")
    print(f"Val split: {len(val_data)}")
    print(f"Output saved to: {OUTPUT_DATASET_DIR}")

if __name__ == "__main__":
    build_yolo_dataset()
