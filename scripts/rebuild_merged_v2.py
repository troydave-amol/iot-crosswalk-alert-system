import os
import cv2
import zipfile
import shutil
from pathlib import Path

# Paths
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
ZIP_ROOT = PROJECT_ROOT / "datasets" / "exports"
OUTPUT_DATASET = PROJECT_ROOT / "datasets" / "merged_v2"
CAMERA_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\CAMERA\VIDEOS")

# Map special AFT patterns back to the actual CCTV raw folders.
def map_aft_to_video(stem_part):
    # e.g., "aft_400_445_02"
    parts = stem_part.split('_')
    time_folder = f"{parts[1][0]},{parts[1][1:3]}pm - {parts[2][0]},{parts[2][1:3]}pm"
    video_num = str(int(parts[3])) + ".mp4"
    return CAMERA_ROOT / "Afternoon_V1" / time_folder / video_num

def setup_merged_yolo():
    (OUTPUT_DATASET / "images" / "train").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DATASET / "labels" / "train").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DATASET / "images" / "val").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DATASET / "labels" / "val").mkdir(parents=True, exist_ok=True)

def strip_ls_hash(filename):
    if "__" in filename:
        return filename.split("__", 1)[1]
    return filename

def reconstruct_dataset():
    setup_merged_yolo()
    total_processed = 0

    zips = [
        ("Afternoon_V2", ZIP_ROOT / "Afternoon_V2.zip"),
        ("Afternoon_V1", ZIP_ROOT / "Afternoon_V1.zip"),
        ("Morning_V1", ZIP_ROOT / "Morning_V1.zip")
    ]

    for name, zip_path in zips:
        if not zip_path.exists():
            print(f"[SKIP] Zip not found: {zip_path}")
            continue

        print(f"\nProcessing {name}...")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            txt_files = [f for f in zf.namelist() if f.startswith('labels/') and f.endswith('.txt')]
            
            for txt_name in txt_files:
                # 1. Read Label Studio text
                content = zf.read(txt_name).decode('utf-8').strip()
                if not content: continue # Skip completely empty backgrounds without pedestrians
                
                pure_txt_name = strip_ls_hash(Path(txt_name).name)
                pure_stem = Path(pure_txt_name).stem
                
                # 2. Extract matching image mathematically
                img_out_path = OUTPUT_DATASET / "images" / "train" / f"{pure_stem}.jpg"
                txt_out_path = OUTPUT_DATASET / "labels" / "train" / pure_txt_name
                
                if img_out_path.exists():
                    total_processed += 1
                    continue

                if "AftV2" in pure_stem:
                    # Afternoon V2 -> Already cleanly extracted recently on hard drive!
                    # Search specifically for it inside datasets/afternoon_v2/frames_raw
                    search_path = PROJECT_ROOT / "datasets" / "afternoon_v2" / "frames_raw"
                    found = list(search_path.rglob(f"{pure_stem}.jpg"))
                    if found:
                        shutil.copy(str(found[0]), str(img_out_path))
                    else:
                        print(f"  Missing V2 image globally: {pure_stem}")

                else:
                    # V1 -> Surgically Re-extract directly from raw CCTV based on filename regex math
                    import re
                    def parse_filename(pure_stem):
                        m1 = re.match(r"dense_(aft_\d+_\d+_\d+)_0*(\d+)s", pure_stem)
                        if m1: return m1.group(1), float(m1.group(2)), True
                        m2 = re.match(r"(aft_\d+_\d+_\d+)_dense_\d+_t(\d+)s", pure_stem)
                        if m2: return m2.group(1), float(m2.group(2)), True
                        m3 = re.match(r"(aft_\d+_\d+_\d+)_dense_(\d+\.?\d*)s", pure_stem)
                        if m3: return m3.group(1), float(m3.group(2)), True
                        m4 = re.match(r"(aft_\d+_\d+_\d+)_dense_(\d+)s_(\d+)s_(\d+)", pure_stem)
                        if m4: return m4.group(1), float(m4.group(2)) + int(m4.group(4)), True
                        m_sparse = re.match(r"(aft_\d+_\d+_\d+)_0*(\d+)", pure_stem)
                        if m_sparse: return m_sparse.group(1), int(m_sparse.group(2)), False
                        # Morning V1 directly
                        m_morn = re.match(r"(\d{3}\.\d{3}\.\d\.\d{2}_\d{2}_\d+_\d+)_0*(\d+)", pure_stem)
                        if m_morn: return m_morn.group(1), int(m_morn.group(2)), False
                        return None, None, None
                        
                    v_stem, val, is_dense = parse_filename(pure_stem)
                    
                    if v_stem is None:
                        print(f"  [SKIP] Unparseable filename syntax lost to time: {pure_stem}")
                        continue
                        
                    if pure_stem.startswith("aft_") or pure_stem.startswith("dense_aft_"):
                        video_path = map_aft_to_video(v_stem)
                        interval = 5
                    else:
                        video_path = CAMERA_ROOT / "Morning_V1" / f"{v_stem}.mp4"
                        interval = 3
                        
                    if video_path and video_path.exists():
                        cap = cv2.VideoCapture(str(video_path))
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        if is_dense:
                            frame_idx = int(val * fps)
                        else:
                            frame_interval = int(fps * interval)
                            frame_idx = int(val * frame_interval)

                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                        ret, frame = cap.read()
                        if ret:
                            cv2.imwrite(str(img_out_path), frame)
                        cap.release()
                    else:
                        print(f"  Missing root video: {video_path}")

                
                # 3. Write txt file
                if img_out_path.exists():
                    with open(txt_out_path, 'w') as f:
                        f.write(content)
                    total_processed += 1
                else:
                    print(f"Failed to generate: {pure_stem}")

    print(f"\n[DONE] Successfully fully reconstructed {total_processed} items inside datasets/merged_v2/ !")
    
    # Generate classes.txt
    classes_content = "child\nadult\n"
    with open(OUTPUT_DATASET / "classes.txt", 'w') as f:
        f.write(classes_content)
    
if __name__ == "__main__":
    reconstruct_dataset()
