"""
prepare_august11_combined_dataset.py
────────────────────────────────────────────────────────────────
Combines:
1. Batches 1-15 (1,500 frames from 'Trained (1-15)')
2. Batches 16-52 (1,800 newly annotated frames from 'August_11_2026')
Total: 33 batches = 3,300 frames.

Splits into:
- 80% Train: 2,640 images + labels
- 20% Val:   660 images + labels

Outputs to:
  datasets/02_yolo_dataset/august11_33_batches/
────────────────────────────────────────────────────────────────
"""

import os
import re
import shutil
import random
import zipfile
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT  = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
EXPORTS_DIR   = PROJECT_ROOT / "datasets" / "01_label_studio_exports" / "August_11_2026"
TRAINED_DIR   = EXPORTS_DIR / "Trained (1-15)"
FRAMES_DIR    = PROJECT_ROOT / "datasets" / "August 11, 2026 Frames"
OUTPUT_DIR    = PROJECT_ROOT / "datasets" / "02_yolo_dataset" / "august11_33_batches"
TMP_DIR       = OUTPUT_DIR / "tmp_extracted"

SPLIT_RATIO   = 0.80  # 80% train, 20% validation
CLASSES       = ["adult", "child"]  # 0: adult, 1: child (Canonical Runtime Truth)
# ───────────────────────────────────────────────────────────────


def process_zip_list(zip_files, image_lookup, label_source_desc):
    dataset_pairs = []
    missing_images = []

    print(f"\nProcessing {len(zip_files)} batch zips ({label_source_desc})...")
    for z_path in zip_files:
        batch_name = z_path.stem
        batch_tmp = TMP_DIR / batch_name
        batch_tmp.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(z_path, "r") as z:
            z.extractall(batch_tmp)

        labels_dir = batch_tmp / "labels"
        if not labels_dir.exists():
            # Check if labels are in root of zip
            label_files = [f for f in batch_tmp.glob("*.txt") if not f.name.endswith("classes.txt")]
        else:
            label_files = [f for f in labels_dir.glob("*.txt") if not f.name.endswith("classes.txt")]

        matched_in_batch = 0
        for lf in label_files:
            clean_name = re.sub(r"^[a-f0-9]{8}__", "", lf.name)
            img_name = clean_name.replace(".txt", ".jpg")

            if img_name in image_lookup:
                dataset_pairs.append({
                    "clean_name": f"{batch_name}_{clean_name.replace('.txt', '')}",
                    "img_src": image_lookup[img_name],
                    "label_src": lf
                })
                matched_in_batch += 1
            else:
                missing_images.append((batch_name, img_name))

        print(f"  {batch_name}: matched {matched_in_batch} / {len(label_files)} labels.")

    return dataset_pairs, missing_images


def main():
    print("=" * 65)
    print("PREPARING COMBINED AUGUST 11 YOLO DATASET (3,300 FRAMES)")
    print("=" * 65)

    old_zips = sorted(TRAINED_DIR.glob("batch_*.zip"))
    new_zips = sorted(EXPORTS_DIR.glob("batch_*.zip"))

    print(f"Original Batches (1-15):  {len(old_zips)} zips (1,500 frames)")
    print(f"New Batches (16-52):      {len(new_zips)} zips (1,800 frames)")
    print(f"Total Batches to Combine: {len(old_zips) + len(new_zips)} zips (3,300 frames)")

    if len(new_zips) != 18:
        print(f"[WARN] Expected 18 new zips, found {len(new_zips)}")

    # 1. Reset output directory
    if OUTPUT_DIR.exists():
        print(f"\nCleaning existing output directory: {OUTPUT_DIR}")
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

    # 3. Extract and match pairs
    old_pairs, old_missing = process_zip_list(old_zips, image_lookup, "Batches 1-15")
    new_pairs, new_missing = process_zip_list(new_zips, image_lookup, "Batches 16-52")

    all_pairs = old_pairs + new_pairs
    all_missing = old_missing + new_missing

    print("\n" + "=" * 65)
    print(f"EXTRACTION SUMMARY:")
    print(f"Batches 1-15 pairs:  {len(old_pairs)} frames")
    print(f"Batches 16-52 pairs: {len(new_pairs)} frames")
    print(f"Total Combined:      {len(all_pairs)} frames")
    if all_missing:
        print(f"[WARNING] Missing images: {len(all_missing)}")
    print("=" * 65)

    # 4. Shuffle & Split (Seed 42 for reproducibility)
    random.seed(42)
    random.shuffle(all_pairs)

    train_count = int(len(all_pairs) * SPLIT_RATIO)
    train_pairs = all_pairs[:train_count]
    val_pairs   = all_pairs[train_count:]

    def copy_split(pairs, split_name):
        print(f"Writing {len(pairs)} frames to {split_name} split...")
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
    print(f"Train images: {len(train_pairs)} (80%)")
    print(f"Val images:   {len(val_pairs)} (20%)")
    print(f"Total:        {len(all_pairs)} frames")
    print(f"Dataset YAML: {yaml_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
