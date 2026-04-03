import cv2
import os
import random
from pathlib import Path

# Config
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_ROOT = PROJECT_ROOT / "datasets" / "02_yolo_dataset"
IMAGES_DIR = DATASET_ROOT / "images" / "train"
LABELS_DIR = DATASET_ROOT / "labels" / "train"
OUTPUT_DIR = PROJECT_ROOT / "datasets" / "visual_verify_output"

CLASSES = ['adult', 'child']
COLORS = [(255, 180, 50), (0, 255, 255)]  # Dashboard colors: Orange for adult, Cyan for child

def verify_dataset():
    if not IMAGES_DIR.exists():
        print(f"[ERROR] Cannot find dataset at: {IMAGES_DIR}")
        print("Please make sure the dataset was extracted correctly into 02_yolo_dataset.")
        return

    # Clean old temp output if exists
    if OUTPUT_DIR.exists():
        for file in OUTPUT_DIR.glob("*.jpg"):
            file.unlink()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get all dataset images
    all_images = list(IMAGES_DIR.glob("*.jpg"))
    if not all_images:
        print(f"[ERROR] No JPG images found in {IMAGES_DIR}!")
        return

    # Pick 20 random images to test alignment
    sample = random.sample(all_images, min(20, len(all_images)))
    
    for img_path in sample:
        label_path = LABELS_DIR / f"{img_path.stem}.txt"
        
        img = cv2.imread(str(img_path))
        if img is None: 
            continue
        
        h, w = img.shape[:2]
        
        if label_path.exists():
            with open(label_path, 'r') as f:
                lines = f.readlines()
            
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 5:
                    class_id = int(parts[0])
                    # YOLO format: center_x, center_y, width, height (normalized 0 to 1)
                    cx, cy, bw, bh = map(float, parts[1:5])
                    
                    # Convert to pixel coordinates
                    px = int((cx - bw / 2) * w)
                    py = int((cy - bh / 2) * h)
                    px_max = int((cx + bw / 2) * w)
                    py_max = int((cy + bh / 2) * h)
                    
                    color = COLORS[class_id] if class_id < len(COLORS) else (0, 255, 0)
                    label_name = CLASSES[class_id] if class_id < len(CLASSES) else f"Class {class_id}"
                    
                    cv2.rectangle(img, (px, py), (px_max, py_max), color, 3)
                    
                    # Professional styled text background block
                    (tw, th), _ = cv2.getTextSize(label_name, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                    cv2.rectangle(img, (px, max(0, py - th - 10)), (px + tw + 10, py), color, -1)
                    # Draw text inside background block (black for high contrast)
                    cv2.putText(img, label_name, (px + 5, py - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2, cv2.LINE_AA)
        
        # Save output
        out_file = OUTPUT_DIR / f"{img_path.name}"
        cv2.imwrite(str(out_file), img)
        
    print(f"[SUCCESS] Analyzed {len(sample)} random dataset images.")
    print(f"You can visually inspect the YOLO labels here: {OUTPUT_DIR}")

if __name__ == "__main__":
    verify_dataset()
