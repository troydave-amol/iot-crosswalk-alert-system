import os
import shutil
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
SOURCE_DIR = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\source_afternoon_v2\raw_frames")
BATCH_SIZE = 100
# ───────────────────────────────────────────────────────────────

def batch_reorganize():
    # 1. Grab every single JPG file recursively from SOURCE_DIR 
    all_images = sorted(list(SOURCE_DIR.rglob("*.jpg")))
    total_found = len(all_images)
    
    if total_found == 0:
        print(f"No JPG files found in {SOURCE_DIR}")
        return

    print(f"Found {total_found} images. Starting reorganization into subfolders of {BATCH_SIZE}...")

    # 2. Reorganize into batches
    for i in range(0, total_found, BATCH_SIZE):
        batch_start = i + 1
        batch_end = min(i + BATCH_SIZE, total_found)
        
        folder_name = f"batch_{batch_start:03d}_{batch_end:03d}"
        dest_folder = SOURCE_DIR / folder_name
        dest_folder.mkdir(exist_ok=True)
        
        batch_files = all_images[i:i + BATCH_SIZE]
        print(f"Moving {len(batch_files)} images into {dest_folder.name}...")
        
        for file_path in batch_files:
            # We want to move it to the new batch folder
            # If the file is already in a subfolder (like the dense one), we move it to the new flat batch folder
            dest_path = dest_folder / file_path.name
            
            # If multiple files have exactly the same name (unlikely given our prefixes but just in case)
            if dest_path.exists():
                print(f"  [NOTICE] Duplicate name found: {file_path.name}. Renaming to avoid overwrite.")
                dest_path = dest_folder / f"dup_{file_path.name}"
                
            shutil.move(str(file_path), str(dest_path))

    # 3. Cleanup empty subdirectories (like the old 'dense' segment folder)
    print("\nCleaning up empty subdirectories...")
    for entry in os.scandir(SOURCE_DIR):
        if entry.is_dir():
            # Only remove it if it's NOT one of our new batch folders
            if not entry.name.startswith("batch_"):
                # We check if it's empty
                if not any(Path(entry.path).rglob('*')):
                    print(f"Removing empty source folder: {entry.name}")
                    os.rmdir(entry.path)

    print("\nReorganization Complete!")
    print(f"Output: {SOURCE_DIR}")

if __name__ == "__main__":
    batch_reorganize()
