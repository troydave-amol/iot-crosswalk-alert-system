import os
import shutil
import zipfile
import re
import random
import glob

# Configuration
PROJECT_ROOT = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics"
ZIP_FILE = os.path.join(PROJECT_ROOT, "datasets", "source_afternoon_v1", "annotation_exports", "afternoon_v1_label_studio_yolo_export.zip")
FRAMES_BASE_DIR = os.path.join(PROJECT_ROOT, "datasets", "source_afternoon_v1", "selected_frames")
YOLO_DATASET_DIR = os.path.join(PROJECT_ROOT, "datasets", "source_afternoon_v1", "yolo_dataset")
TMP_UNZIP_DIR = os.path.join(YOLO_DATASET_DIR, "tmp_unzip")

SPLIT_RATIO = 0.8  # 80% train, 20% validation

# Classes (from what you set up in Label Studio)
CLASSES = ["adult", "child"]

def find_original_image(filename):
    """Search for the original image in the selected_frames subdirectories."""
    # Could be in batch_001_100, batch_101_200, batch_201_250
    search_path = os.path.join(FRAMES_BASE_DIR, "**", filename)
    matches = glob.glob(search_path, recursive=True)
    if matches:
        return matches[0]
    return None

def main():
    print(f"--- Preparing YOLOv8 Dataset ---")
    
    # 1. Clean previous runs
    if os.path.exists(YOLO_DATASET_DIR):
        print(f"Cleaning existing directory: {YOLO_DATASET_DIR}")
        shutil.rmtree(YOLO_DATASET_DIR)
        
    os.makedirs(TMP_UNZIP_DIR, exist_ok=True)
    
    # Create train and val directories
    for split in ['train', 'val']:
        os.makedirs(os.path.join(YOLO_DATASET_DIR, split, 'images'), exist_ok=True)
        os.makedirs(os.path.join(YOLO_DATASET_DIR, split, 'labels'), exist_ok=True)
        
    # 2. Extract ZIP
    print(f"Extracting {ZIP_FILE}...")
    with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
        zip_ref.extractall(TMP_UNZIP_DIR)
        
    # 3. Process labels and images
    labels_dir = os.path.join(TMP_UNZIP_DIR, 'labels')
    label_files = [f for f in os.listdir(labels_dir) if f.endswith('.txt')]
    print(f"Found {len(label_files)} label files.")
    
    # We will gather all valid pairs
    dataset_pairs = []
    missing_images = []
    
    for lf in label_files:
        # Label Studio prefixes files with an 8-character hex code + "__" (e.g., 0e456327__aft_245...)
        clean_filename = re.sub(r'^[a-f0-9]{8}__', '', lf)
        image_filename = clean_filename.replace('.txt', '.jpg')
        
        orig_img_path = find_original_image(image_filename)
        
        if orig_img_path is not None:
            dataset_pairs.append({
                'label_src': os.path.join(labels_dir, lf),
                'img_src': orig_img_path,
                'clean_name': clean_filename.replace('.txt', '')
            })
        else:
            missing_images.append(image_filename)
            
    print(f"Successfully matched {len(dataset_pairs)} images.")
    if missing_images:
        print(f"WARNING: Could not find original images for {len(missing_images)} files.")
        
    # 4. Shuffle and Split
    random.seed(42)  # For reproducibility
    random.shuffle(dataset_pairs)
    
    train_split_idx = int(len(dataset_pairs) * SPLIT_RATIO)
    train_pairs = dataset_pairs[:train_split_idx]
    val_pairs = dataset_pairs[train_split_idx:]
    
    # Helper to copy files
    def copy_split(pairs, split_name):
        print(f"Copying {len(pairs)} pairs to {split_name}...")
        for p in pairs:
            # Destination paths
            dest_img = os.path.join(YOLO_DATASET_DIR, split_name, 'images', p['clean_name'] + '.jpg')
            dest_lbl = os.path.join(YOLO_DATASET_DIR, split_name, 'labels', p['clean_name'] + '.txt')
            
            # Copy Image
            shutil.copy2(p['img_src'], dest_img)
            # Copy Label
            shutil.copy2(p['label_src'], dest_lbl)

    copy_split(train_pairs, 'train')
    copy_split(val_pairs, 'val')
    
    # 5. Generate dataset.yaml
    yaml_path = os.path.join(YOLO_DATASET_DIR, 'dataset.yaml')
    with open(yaml_path, 'w') as f:
        f.write(f"path: {os.path.abspath(YOLO_DATASET_DIR)}\n")
        f.write(f"train: train/images\n")
        f.write(f"val: val/images\n")
        f.write(f"\n")
        f.write(f"names:\n")
        for i, class_name in enumerate(CLASSES):
            f.write(f"  {i}: {class_name}\n")
            
    print(f"Generated {yaml_path}")
    
    # Cleanup tmp dir
    shutil.rmtree(TMP_UNZIP_DIR)
    print("Done! Dataset is ready for YOLOv8 fine-tuning.")

if __name__ == "__main__":
    main()
