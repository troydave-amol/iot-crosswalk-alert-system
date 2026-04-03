import os
import shutil
import zipfile
import re
import random
import glob
from pathlib import Path

# Configuration
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")

# Afternoon Dataset Details
AFT_ZIP = (
    PROJECT_ROOT
    / "datasets"
    / "source_afternoon_v1"
    / "annotation_exports"
    / "afternoon_v1_label_studio_yolo_export.zip"
)
AFT_FRAMES_DIR = PROJECT_ROOT / "datasets" / "source_afternoon_v1" / "selected_frames"

# Morning Dataset Details
MORN_ZIP = (
    PROJECT_ROOT
    / "datasets"
    / "source_morning_v1"
    / "annotation_exports"
    / "morning_v1_label_studio_yolo_export.zip"
)
MORN_FRAMES_DIR = PROJECT_ROOT / "datasets" / "source_morning_v1" / "selected_frames"

# Final Merged Dataset Output
MERGED_DATASET_DIR = PROJECT_ROOT / "datasets" / "merged_dataset_v1" / "yolo_dataset"
TMP_UNZIP_DIR = MERGED_DATASET_DIR / "tmp_unzip"

SPLIT_RATIO = 0.8  # 80% train, 20% validation

# Ensure index 0 = adult, 1 = child to match Label Studio's default ordering output
CLASSES = ["adult", "child"]

def find_original_image(filename, search_base_dir):
    """Deep search for the original image in the base directory."""
    search_path = search_base_dir / "**" / filename
    matches = glob.glob(str(search_path), recursive=True)
    if matches:
        return matches[0]
    return None

def process_zip(zip_path, frames_base_dir, origin_name):
    print(f"\n--- Processing {origin_name} Dataset ---")
    tmp_dir = TMP_UNZIP_DIR / origin_name
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Extracting {zip_path.name}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(tmp_dir)
        
    labels_dir = tmp_dir / 'labels'
    if not labels_dir.exists():
        print(f"[ERROR] No 'labels' folder found in {zip_path.name}. Ensure it was exported as YOLO format.")
        return []

    label_files = [f.name for f in labels_dir.glob("*.txt")]
    print(f"Found {len(label_files)} label files.")
    
    dataset_pairs = []
    missing_images = []
    
    for lf in label_files:
        # Label Studio YOLO exports prefix files with an 8-character hex code + "__"
        clean_filename = re.sub(r'^[a-f0-9]{8}__', '', lf)
        image_filename = clean_filename.replace('.txt', '.jpg')
        
        orig_img_path = find_original_image(image_filename, frames_base_dir)
        
        if orig_img_path is not None:
            dataset_pairs.append({
                'label_src': labels_dir / lf,
                'img_src': Path(orig_img_path),
                'clean_name': clean_filename.replace('.txt', ''),
                'origin': origin_name
            })
        else:
            missing_images.append(image_filename)
            
    print(f"Successfully matched: {len(dataset_pairs)} images.")
    if missing_images:
        print(f"WARNING: Missing images for {len(missing_images)} files in {origin_name}. Examples:")
        for m in missing_images[:5]:
            print(f"  - {m}")
            
    return dataset_pairs


def main():
    print("=== Merging Databases (Morning + Afternoon) for YOLOv8 ===")
    
    # 1. Clean previous runs
    if MERGED_DATASET_DIR.exists():
        print(f"Cleaning existing directory: {MERGED_DATASET_DIR}")
        shutil.rmtree(MERGED_DATASET_DIR)
        
    TMP_UNZIP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create train and val directories
    for split in ['train', 'val']:
        (MERGED_DATASET_DIR / split / 'images').mkdir(parents=True, exist_ok=True)
        (MERGED_DATASET_DIR / split / 'labels').mkdir(parents=True, exist_ok=True)
        
    # 2. Extract and Process both ZIPs
    all_pairs = []
    all_pairs.extend(process_zip(AFT_ZIP, AFT_FRAMES_DIR, "afternoon_v1"))
    all_pairs.extend(process_zip(MORN_ZIP, MORN_FRAMES_DIR, "morning_v1"))
    
    print(f"\nTotal Merged Image Pairs: {len(all_pairs)}")
    
    if len(all_pairs) == 0:
        print("Error: No images found. Aborting.")
        return

    # 3. Shuffle and split
    random.seed(42)
    random.shuffle(all_pairs)
    
    train_split_idx = int(len(all_pairs) * SPLIT_RATIO)
    train_pairs = all_pairs[:train_split_idx]
    val_pairs = all_pairs[train_split_idx:]
    
    print(f"\n--- Splitting Dataset ---")
    print(f"Train Set: {len(train_pairs)} images")
    print(f"Val Set: {len(val_pairs)} images")
    
    def copy_split(pairs, split_name):
        for p in pairs:
            unique_name = p["clean_name"]
            if not unique_name.startswith((f"{p['origin']}_", "afternoon_v1_", "morning_v1_")):
                unique_name = f"{p['origin']}_{unique_name}"
            
            dest_img = MERGED_DATASET_DIR / split_name / 'images' / (unique_name + '.jpg')
            dest_lbl = MERGED_DATASET_DIR / split_name / 'labels' / (unique_name + '.txt')
            
            shutil.copy2(p['img_src'], dest_img)
            shutil.copy2(p['label_src'], dest_lbl)

    copy_split(train_pairs, 'train')
    copy_split(val_pairs, 'val')
    
    # 4. Generate dataset.yaml
    yaml_path = MERGED_DATASET_DIR / 'dataset.yaml'
    with open(yaml_path, 'w') as f:
        # Using relative paths for standard YOLOv8 format! 
        f.write(f"path: {MERGED_DATASET_DIR.resolve()}\n")
        f.write("train: train/images\n")
        f.write("val: val/images\n\n")
        f.write("names:\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"  {i}: {class_name}\n")
            
    print(f"\nGenerated unified YAML configuration: {yaml_path}")
    
    # Cleanup tmp dir
    shutil.rmtree(TMP_UNZIP_DIR)
    print("\nSUCCESS! Your golden dataset (Morning + Afternoon) is fully prepared and merged for Colab training!")

if __name__ == "__main__":
    main()
