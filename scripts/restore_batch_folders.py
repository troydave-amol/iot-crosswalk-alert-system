import os
import shutil
from pathlib import Path

SOURCE_DIR = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\source_afternoon_v2\raw_frames")
OUTPUT_DIR = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\afternoon_v2\frames_raw")

def split_frames():
    # Gather ALL newly extracted .jpg files we just created
    all_images = list(SOURCE_DIR.rglob("*.jpg"))
    # Sort them by name deterministically so they get the same order as before!
    all_images.sort(key=lambda p: p.name)
    
    print(f"Found {len(all_images)} newly extracted images.")
    
    # Recreate the main output directory if it doesn't exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    batch_size = 100
    total_imgs = len(all_images)
    
    for i in range(0, total_imgs, batch_size):
        start = i + 1
        end = min(i + batch_size, total_imgs)
        
        # Format the exact folder name matching earlier today (e.g., 1-100, 301-319)
        folder_name = f"{start}-{end}"
        batch_dir = OUTPUT_DIR / folder_name
        batch_dir.mkdir(exist_ok=True)
        
        # Copy the images into the batch folder
        batch_images = all_images[i:i+batch_size]
        for img_path in batch_images:
            shutil.copy2(img_path, batch_dir / img_path.name)
            
        print(f"Copied {len(batch_images)} images into {folder_name}/")

if __name__ == "__main__":
    split_frames()
