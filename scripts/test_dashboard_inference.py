import os
import cv2
import random
import sys
from pathlib import Path

# Fix relative imports for cv_inference which is defined in the root folder
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
sys.path.insert(0, str(PROJECT_ROOT))

from cv_inference import ChildLikeDetector, ROI

ARTIFACT_DIR = Path(r"C:\Users\Acer\.gemini\antigravity\brain\d9180c1b-6c56-4f1b-9e8f-c47e989b92ed")
MODEL_PATH = PROJECT_ROOT / "datasets" / "merged_dataset_v1" / "trained_model" / "weights" / "best.pt"
VAL_IMAGES_DIR = PROJECT_ROOT / "datasets" / "merged_dataset_v1" / "yolo_dataset" / "val" / "images"

def _draw_overlay(frame, detections):
    """Simplified drawing based on app.py logic to visualize our final detector boxes."""
    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        conf = d["conf"]
        cls = d["cls"]
        
        if cls == 1:
            color = (0, 255, 255)  # Cyan for child
            label = f"child_like {conf:.2f}"
            thickness = 3
        else:
            color = (0, 165, 255)  # Orange for adult
            label = f"adult_like {conf:.2f}"
            thickness = 2
            
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), (0, 0, 0), -1)
        cv2.putText(frame, label, (x1 + 3, max(th + 3, y1 - 3)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    return frame


def run_test():
    print("Loading model...")
    detector = ChildLikeDetector(
        str(MODEL_PATH),
        conf_child=0.65,
        min_child_bbox_ratio=0.18,
        dominance_iou=0.70,
        imgsz=640
    )
    
    # Pick 10 random interesting scenes (from val dataset)
    val_files = list(VAL_IMAGES_DIR.glob("*.jpg"))
    import time
    random.seed(int(time.time())) # random seed for entirely new images
    test_files = random.sample(val_files, 10)
    
    for i, img_path in enumerate(test_files):
        print(f"Testing on {img_path.name}")
        frame = cv2.imread(str(img_path))
        if frame is None:
            continue
            
        # create a dummy ROI that covers the whole screen since we just want to test raw boxes
        h, w = frame.shape[:2]
        dummy_roi = ROI(0, 0, w-1, h-1)
        
        # This will use our updated cv_inference.py (conf=0.5, iou=0.45)
        out = detector.infer_frame(frame, dummy_roi)
        
        annotated_frame = _draw_overlay(frame.copy(), out["detections"])
        
        # Save to artifacts
        out_path = ARTIFACT_DIR / f"inference_test_result_{i}.jpg"
        cv2.imwrite(str(out_path), annotated_frame)
        print(f"Saved: {out_path}")

if __name__ == "__main__":
    run_test()
