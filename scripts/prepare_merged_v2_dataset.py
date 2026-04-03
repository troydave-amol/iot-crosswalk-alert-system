import os
import shutil
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")

# Input constituent datasets (must be fully prepared YOLO format)
DATASETS_TO_MERGE = [
    PROJECT_ROOT / "datasets" / "merged_dataset_v1" / "yolo_dataset",
    PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "yolo_dataset"
]

OUTPUT_DATASET_DIR = PROJECT_ROOT / "datasets" / "merged_dataset_v2" / "yolo_dataset"
CLASSES = ["adult", "child"]
# ───────────────────────────────────────────────────────────────

def merge_datasets():
    print(f"Creating merged_dataset_v2 super-dataset at: {OUTPUT_DATASET_DIR}")
    
    if OUTPUT_DATASET_DIR.exists():
        print("Clearing existing merged directory...")
        shutil.rmtree(OUTPUT_DATASET_DIR)
        
    for split in ["train", "val"]:
        (OUTPUT_DATASET_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DATASET_DIR / split / "labels").mkdir(parents=True, exist_ok=True)
        
    total_train = 0
    total_val = 0
    
    for ds_dir in DATASETS_TO_MERGE:
        if not ds_dir.exists():
            print(f"[ERROR] Found missing dataset component: {ds_dir}. Aborting merge!")
            return
            
        print(f"\nProcessing {ds_dir.parent.name}...")
        
        for split in ["train", "val"]:
            img_src = ds_dir / split / "images"
            lbl_src = ds_dir / split / "labels"
            
            img_dst = OUTPUT_DATASET_DIR / split / "images"
            lbl_dst = OUTPUT_DATASET_DIR / split / "labels"
            
            if not img_src.exists() or not lbl_src.exists():
                print(f"  [WARNING] Skipping {split} in {ds_dir.parent.name} (Not found)")
                continue
                
            images = list(img_src.glob("*.jpg")) + list(img_src.glob("*.png"))
            labels = list(lbl_src.glob("*.txt"))
            
            for img_path in images:
                label_path = lbl_src / f"{img_path.stem}.txt"
                
                if label_path.exists():
                    # Copy to merged directory
                    shutil.copy(str(img_path), str(img_dst / img_path.name))
                    shutil.copy(str(label_path), str(lbl_dst / label_path.name))
                    
                    if split == "train":
                        total_train += 1
                    else:
                        total_val += 1
            
            print(f"  Copied {len(images)} {split} frames.")
            
    # Generate unified dataset.yaml
    yaml_path = OUTPUT_DATASET_DIR / "dataset.yaml"
    with open(yaml_path, "w") as f:
        f.write(f"path: {OUTPUT_DATASET_DIR.absolute()}\n")
        f.write("train: train/images\n")
        f.write("val: val/images\n\n")
        f.write("names:\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"  {i}: {class_name}\n")
            
    print(f"\n{'='*50}")
    print(f"MERGED V2 DATASET COMPLETE!")
    print(f"Total Combined Training Images:   {total_train}")
    print(f"Total Combined Validation Images: {total_val}")
    print(f"Grand Total:                      {total_train + total_val}")
    print(f"YAML Config: {yaml_path}")

if __name__ == "__main__":
    merge_datasets()
