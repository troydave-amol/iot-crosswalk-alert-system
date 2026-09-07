"""
prepare_august11_dataset.py
────────────────────────────────────────────────────────────────
Extracts and combines all 15 Label Studio exported ZIP batches
(datasets/01_label_studio_exports/August 11, 2026/batch_*.zip),
matches each label file to its corresponding frame in
'datasets/August 11, 2026 Frames/', and builds a unified YOLO
train/val dataset at 'datasets/august11_yolo_dataset/'.
────────────────────────────────────────────────────────────────
"""

import os
import re
import glob
import shutil
import random
import zipfile
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
EXPORTS_DIR  = PROJECT_ROOT / "datasets" / "01_label_studio_exports" / "August_11_2026"
FRAMES_DIR   = PROJECT_ROOT / "datasets" / "August 11, 2026 Frames"
OUTPUT_DIR   = PROJECT_ROOT / "datasets" / "02_yolo_dataset" / "august11_15_batches"
TMP_DIR      = OUTPUT_DIR / "tmp_extracted"

SPLIT_RATIO  = 0.80  # 80% train, 20% validation
CLASSES      = ["adult", "child"]  # 0: adult, 1: child (Canonical Runtime Truth)
# ───────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("PREPARING AUGUST 11 YOLO DATASET (15 BATCHES)")
    print("=" * 65)

    if not EXPORTS_DIR.exists():
        print(f"[ERROR] Exports folder not found: {EXPORTS_DIR}")
        return

    zip_files = sorted(EXPORTS_DIR.glob("batch_*.zip"))
    if not zip_files:
        print(f"[ERROR] No batch_*.zip files found in {EXPORTS_DIR}")
        return

    print(f"Found {len(zip_files)} batch zip files to process.")

    # 1. Reset output directory
    if OUTPUT_DIR.exists():
        print(f"Cleaning existing output directory: {OUTPUT_DIR}")
        shutil.rmtree(OUTPUT_DIR)

    for split in ["train", "val"]:
        (OUTPUT_DIR / split / "images").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / split / "labels").mkdir(parents=True, exist_ok=True)

    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Build image lookup map across all batch folders
    print("\nIndexing frame image files...")
    image_lookup = {}
    for img_path in FRAMES_DIR.glob("batch_*/*.jpg"):
        image_lookup[img_path.name] = img_path

    print(f"Indexed {len(image_lookup)} source frames.")

    # 3. Extract each zip and collect valid image-label pairs
    dataset_pairs = []
    missing_images = []

    for z_path in zip_files:
        batch_name = z_path.stem
        batch_tmp = TMP_DIR / batch_name
        batch_tmp.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(z_path, "r") as z:
            z.extractall(batch_tmp)

        labels_dir = batch_tmp / "labels"
        if not labels_dir.exists():
            continue

        label_files = list(labels_dir.glob("*.txt"))
        matched_in_batch = 0

        for lf in label_files:
            # Label Studio prepends an 8-hex hash: e.g. "017792ae__frame_00080.txt"
            clean_name = re.sub(r"^[a-f0-9]{8}__", "", lf.name)
            img_name = clean_name.replace(".txt", ".jpg")

            # Look up source image
            if img_name in image_lookup:
                dataset_pairs.append({
                    "clean_name": f"{batch_name}_{clean_name.replace('.txt', '')}",
                    "img_src": image_lookup[img_name],
                    "label_src": lf
                })
                matched_in_batch += 1
            else:
                missing_images.append(img_name)

        print(f"  {batch_name}: matched {matched_in_batch} / {len(label_files)} labels.")

    print(f"\nTotal matched pairs: {len(dataset_pairs)}")
    if missing_images:
        print(f"[WARNING] Missing images for {len(missing_images)} labels.")

    # 4. Shuffle & Split
    random.seed(42)
    random.shuffle(dataset_pairs)

    train_count = int(len(dataset_pairs) * SPLIT_RATIO)
    train_pairs = dataset_pairs[:train_count]
    val_pairs   = dataset_pairs[train_count:]

    def copy_split(pairs, split_name):
        print(f"\nWriting {len(pairs)} frames to {split_name} split...")
        for p in pairs:
            dest_img = OUTPUT_DIR / split_name / "images" / f"{p['clean_name']}.jpg"
            dest_lbl = OUTPUT_DIR / split_name / "labels" / f"{p['clean_name']}.txt"
            shutil.copy2(p["img_src"], dest_img)
            shutil.copy2(p["label_src"], dest_lbl)

    copy_split(train_pairs, "train")
    copy_split(val_pairs, "val")

    # 5. Generate data.yaml
    yaml_path = OUTPUT_DIR / "data.yaml"
    formatted_path = str(OUTPUT_DIR.resolve()).replace("\\", "/")
    yaml_content = f"""path: {formatted_path}
train: train/images
val: val/images

nc: 2
names: ['adult', 'child']
"""
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    # 6. Cleanup temporary extraction dir
    shutil.rmtree(TMP_DIR)

    print("\n" + "=" * 65)
    print("DATASET PREPARATION COMPLETED SUCCESSFULLY!")
    print("=" * 65)
    print(f"Train images: {len(train_pairs)}")
    print(f"Val images:   {len(val_pairs)}")
    print(f"Total:        {len(dataset_pairs)}")
    print(f"Config YAML:  {yaml_path}")
    print("=" * 65)

if __name__ == "__main__":
    main()
