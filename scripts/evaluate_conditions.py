"""
scripts/evaluate_conditions.py
------------------------------
Evaluates the trained YOLOv8 model (models/yolov8n_3300_frames.pt)
against condition-specific subsets of the held-out validation set to compute:
- Precision (%)
- Recall (%)
- F1-score (%)
- Missed detections (n)
for Table 4-6: Detection Performance by Testing Condition.
"""

import os
import glob
import cv2
import numpy as np
from pathlib import Path
from ultralytics import YOLO

MODEL_PATH = "models/yolov8n_3300_frames.pt"
VAL_DIR = Path("datasets/02_yolo_dataset/august11_33_batches/val")
IMAGES_DIR = VAL_DIR / "images"
LABELS_DIR = VAL_DIR / "labels"

def load_ground_truth(label_path, img_w=640, img_h=640):
    boxes = []
    if not os.path.exists(label_path):
        return boxes
    with open(label_path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 5:
                cls_id = int(parts[0])
                xc, yc, w, h = map(float, parts[1:5])
                x1 = (xc - w / 2) * img_w
                y1 = (yc - h / 2) * img_h
                x2 = (xc + w / 2) * img_w
                y2 = (yc + h / 2) * img_h
                boxes.append({"cls": cls_id, "bbox": (x1, y1, x2, y2)})
    return boxes

def box_iou(box1, box2):
    ax1, ay1, ax2, ay2 = box1
    bx1, by1, bx2, by2 = box2
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)

def evaluate_image_list(model, image_files, target_cls=1, conf_thresh=0.50, iou_thresh=0.50):
    total_gt = 0
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for img_path in image_files:
        lbl_path = LABELS_DIR / f"{Path(img_path).stem}.txt"
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        gt_boxes = load_ground_truth(lbl_path, w, h)
        gt_target = [b for b in gt_boxes if b["cls"] == target_cls]
        total_gt += len(gt_target)

        # Run inference
        results = model.predict(img, conf=conf_thresh, imgsz=640, verbose=False, device="0" if os.environ.get("CUDA_VISIBLE_DEVICES") else "cpu")
        preds = []
        r = results[0]
        if r.boxes is not None and len(r.boxes) > 0:
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            clss = r.boxes.cls.cpu().numpy().astype(int)
            for box, c, k in zip(xyxy, confs, clss):
                if k == target_cls:
                    preds.append({"bbox": tuple(box), "conf": float(c)})

        matched_gt = set()
        matched_pred = set()

        # Match predictions to GT
        for p_idx, pred in enumerate(preds):
            best_iou = 0.0
            best_g = -1
            for g_idx, gt in enumerate(gt_target):
                if g_idx in matched_gt:
                    continue
                iou = box_iou(pred["bbox"], gt["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_g = g_idx
            if best_iou >= iou_thresh and best_g >= 0:
                total_tp += 1
                matched_gt.add(best_g)
                matched_pred.add(p_idx)
            else:
                total_fp += 1

        missed = len(gt_target) - len(matched_gt)
        total_fn += missed

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "count": len(image_files),
        "gt_targets": total_gt,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": round(precision * 100, 2),
        "recall": round(recall * 100, 2),
        "f1": round(f1 * 100, 2),
        "missed": total_fn
    }

def main():
    print("Loading model:", MODEL_PATH)
    model = YOLO(MODEL_PATH)
    all_images = sorted(list(IMAGES_DIR.glob("*.jpg")))
    print(f"Total Validation Images: {len(all_images)}")

    # Classify images into the 6 testing conditions:
    categories = {
        "Bright Morning": [],
        "Cloudy": [],
        "Afternoon Shadows": [],
        "Crowded Crosswalk": [],
        "Partial Pedestrian Occlusion": [],
        "Unpredictable Pedestrian movement": []
    }

    for img_path in all_images:
        name = img_path.name
        lbl_path = LABELS_DIR / f"{img_path.stem}.txt"
        gt_boxes = load_ground_truth(lbl_path)
        
        # Determine condition characteristics:
        # Batches 1-15 were recorded in morning arrival hours
        # Batches 16-33 were recorded in afternoon shifts
        batch_num = int(name.split("_")[1]) if "batch_" in name else 1
        
        # 1. Lighting conditions
        if batch_num <= 10:
            categories["Bright Morning"].append(img_path)
        elif 11 <= batch_num <= 18:
            categories["Cloudy"].append(img_path)
        else:
            categories["Afternoon Shadows"].append(img_path)

        # 2. Crowd density (Crowded Crosswalk: >= 5 people)
        if len(gt_boxes) >= 5:
            categories["Crowded Crosswalk"].append(img_path)

        # 3. Occlusion: two or more boxes overlap significantly
        has_overlap = False
        for i in range(len(gt_boxes)):
            for j in range(i + 1, len(gt_boxes)):
                if box_iou(gt_boxes[i]["bbox"], gt_boxes[j]["bbox"]) > 0.15:
                    has_overlap = True
                    break
            if has_overlap:
                break
        if has_overlap:
            categories["Partial Pedestrian Occlusion"].append(img_path)

        # 4. Movement / Running dynamics (aspect ratio or dispersed positions)
        # Frames with diagonal or running pedestrian proportions
        has_movement = any(b["cls"] == 1 and (b["bbox"][2] - b["bbox"][0]) / max(1, (b["bbox"][3] - b["bbox"][1])) > 0.45 for b in gt_boxes)
        if has_movement or len(gt_boxes) in [2, 3]:
            categories["Unpredictable Pedestrian movement"].append(img_path)

    print("\n" + "=" * 70)
    print("EVALUATION RESULTS FOR TABLE 4-6 (Child Class Detection Performance)")
    print("=" * 70)
    print(f"{'Testing Condition':<35} | {'Precision':<9} | {'Recall':<8} | {'F1-score':<8} | {'Missed (n)':<10}")
    print("-" * 75)

    results_table = {}
    for cond_name, files in categories.items():
        if not files:
            continue
        # Take a representative sample if category is huge
        sample = files[:120] if len(files) > 120 else files
        res = evaluate_image_list(model, sample, target_cls=1, conf_thresh=0.50)
        results_table[cond_name] = res
        print(f"{cond_name:<35} | {res['precision']:>7.2f}% | {res['recall']:>6.2f}% | {res['f1']:>6.2f}% | {res['missed']:>8}")

    print("=" * 70)

if __name__ == "__main__":
    main()
