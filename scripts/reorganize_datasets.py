"""
Dataset Folder Cleanup & Reorganization
========================================
Reorganizes the datasets/ directory into a clean, professional structure:

BEFORE:
  datasets/
    afternoon_v2/          (staging - raw frames for Label Studio)
    source_afternoon_v2/   (staging - raw frames)
    merged_dataset_v2/     (old empty skeleton)
    merged_v2/             (actual dataset + training results)
    exports/               (Label Studio ZIP exports)
    README.md

AFTER:
  datasets/
    01_label_studio_exports/     (ZIP backups from Label Studio)
    02_yolo_dataset/             (final 1,111 image+label pairs)
      images/train/
      labels/train/
      data.yaml
      classes.txt
    03_training_runs/            (all YOLO training output)
      run_2025_04_03_merged_v2/  (renamed from run_v2)
        weights/
          best.pt
          last.pt
        results.csv
        results.png
        ...
    04_raw_frames_backup/        (re-extracted frames for Label Studio reference)
      afternoon_v2/
    README.md
"""

import shutil
from pathlib import Path

ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets")

def main():
    print("=" * 60)
    print("DATASET FOLDER REORGANIZATION")
    print("=" * 60)

    # ── Step 1: Create new structure ─────────────────────────
    print("\n[1/6] Creating new directory structure...")
    
    new_exports = ROOT / "01_label_studio_exports"
    new_dataset = ROOT / "02_yolo_dataset"
    new_runs    = ROOT / "03_training_runs"
    new_raw     = ROOT / "04_raw_frames_backup"
    
    new_exports.mkdir(exist_ok=True)
    new_dataset.mkdir(exist_ok=True)
    new_runs.mkdir(exist_ok=True)
    new_raw.mkdir(exist_ok=True)
    print("  Done.")

    # ── Step 2: Move Label Studio exports ────────────────────
    print("\n[2/6] Moving Label Studio exports...")
    old_exports = ROOT / "exports"
    if old_exports.exists():
        for f in old_exports.glob("*.zip"):
            dest = new_exports / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
                print(f"  Moved: {f.name}")
            else:
                print(f"  Already exists: {f.name}")
        # Remove old empty folder
        shutil.rmtree(str(old_exports), ignore_errors=True)
    print("  Done.")

    # ── Step 3: Move YOLO dataset (images + labels + config) ─
    print("\n[3/6] Moving YOLO dataset...")
    old_merged = ROOT / "merged_v2"
    
    if old_merged.exists():
        # Move images
        src_images = old_merged / "images"
        dst_images = new_dataset / "images"
        if src_images.exists() and not dst_images.exists():
            shutil.move(str(src_images), str(dst_images))
            print("  Moved: images/")
        
        # Move labels
        src_labels = old_merged / "labels"
        dst_labels = new_dataset / "labels"
        if src_labels.exists() and not dst_labels.exists():
            shutil.move(str(src_labels), str(dst_labels))
            print("  Moved: labels/")
        
        # Move config files
        for cfg_name in ["data.yaml", "classes.txt"]:
            src = old_merged / cfg_name
            if src.exists():
                shutil.move(str(src), str(new_dataset / cfg_name))
                print(f"  Moved: {cfg_name}")
    print("  Done.")

    # ── Step 4: Move training runs ───────────────────────────
    print("\n[4/6] Moving training runs...")
    old_run = old_merged / "training_runs" / "run_v2"
    new_run_name = "run_2026_04_03_merged_v2"
    dst_run = new_runs / new_run_name
    
    if old_run.exists() and not dst_run.exists():
        shutil.move(str(old_run), str(dst_run))
        print(f"  Moved: run_v2 -> {new_run_name}")
        
        # Rename best.pt for clarity
        best_src = dst_run / "weights" / "best.pt"
        best_dst = dst_run / "weights" / "best_merged_v2_1111imgs.pt"
        if best_src.exists() and not best_dst.exists():
            shutil.copy2(str(best_src), str(best_dst))
            print(f"  Copied: best.pt -> best_merged_v2_1111imgs.pt (kept original too)")
    print("  Done.")

    # ── Step 5: Keep raw frames backup (afternoon_v2 only) ───
    print("\n[5/6] Backing up raw frames...")
    old_aft = ROOT / "afternoon_v2"
    dst_aft = new_raw / "afternoon_v2_frames"
    if old_aft.exists() and not dst_aft.exists():
        shutil.move(str(old_aft), str(dst_aft))
        print("  Moved: afternoon_v2 -> 04_raw_frames_backup/afternoon_v2_frames")
    print("  Done.")

    # ── Step 6: Delete unnecessary folders ───────────────────
    print("\n[6/6] Cleaning up unnecessary folders...")
    
    junk = [
        ROOT / "merged_dataset_v2",       # Old empty skeleton
        ROOT / "source_afternoon_v2",      # Duplicate staging frames
        ROOT / "merged_v2",                # Now empty after moves
    ]
    
    for folder in junk:
        if folder.exists():
            shutil.rmtree(str(folder), ignore_errors=True)
            print(f"  Deleted: {folder.name}/")
    
    # Delete visual_check folder (was temporary)
    vc = new_dataset / "visual_check"  
    if not vc.exists():
        vc = ROOT / "merged_v2" / "visual_check"
    if vc.exists():
        shutil.rmtree(str(vc), ignore_errors=True)
        print("  Deleted: visual_check/")
    
    print("  Done.")

    # ── Step 7: Update data.yaml with new path ───────────────
    print("\n[FINAL] Updating data.yaml with new path...")
    data_yaml = new_dataset / "data.yaml"
    if data_yaml.exists():
        content = f"""path: {str(new_dataset).replace(chr(92), '/')}
train: images/train
val: images/train

nc: 2
names: ['adult', 'child']
"""
        data_yaml.write_text(content)
        print(f"  Updated: data.yaml -> {new_dataset}")

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("REORGANIZATION COMPLETE")
    print("=" * 60)
    print(f"""
NEW STRUCTURE:
  datasets/
    01_label_studio_exports/   <- ZIP backups
    02_yolo_dataset/           <- 1,111 images + labels + data.yaml
    03_training_runs/          <- Training output & model weights
      {new_run_name}/
        weights/
          best.pt
          best_merged_v2_1111imgs.pt
    04_raw_frames_backup/      <- Re-extracted frames (Label Studio ref)
    README.md
""")

if __name__ == "__main__":
    main()
