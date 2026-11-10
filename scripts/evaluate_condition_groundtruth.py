"""
scripts/evaluate_condition_groundtruth.py
=========================================
Evaluates the trained YOLOv8n model (models/yolov8n_3300_frames.pt)
against independent, manual Label Studio ground-truth annotations
across the 7 environmental conditions collected for Objective 4.

Conditions Evaluated (135 total frames):
  1. Crowded Crosswalk Scenes (25 frames)
  2. Partial Occlusion (25 frames)
  3. Unpredictable Child Movement (25 frames)
  4. Overcast or Diffused Lighting (15 frames)
  5. Normal Daylight (15 frames)
  6. Morning Glare (Lens Flare) (15 frames)
  7. Strong Shadows (High Contrast) (15 frames)

Metric Calculation Protocol:
  - Standard IoU matching threshold: >= 0.50
  - Operational child confidence threshold: 0.65 (LIVE_CHILD_CONF)
  - Baseline comparison threshold: 0.50 (Standard VOC benchmark)
  - TP + FN = Total Ground-Truth Child Instances (mathematically guaranteed)
  - Outputs: JSON results artifact and complete Markdown table for Chapter 4
"""

import os
import sys
import json
import zipfile
import datetime
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

# Project paths
PROJECT_ROOT = Path(r"c:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
DATASET_BASE = Path(r"C:\Users\Acer\Documents\CAPSTONE\Condition Evaluation")
MODEL_PATH = PROJECT_ROOT / "models" / "yolov8n_3300_frames.pt"
OUTPUT_JSON = PROJECT_ROOT / "scripts" / "condition_evaluation_results.json"

# Define the 7 target categories and their folder names
CATEGORIES = [
    {
        "id": "01_crowded",
        "display_name": "1. Crowded Crosswalk Scenes",
        "folder": "Crowded Crosswalk Scenes",
        "expected_frames": 25,
    },
    {
        "id": "02_occlusion",
        "display_name": "2. Partial Occlusion",
        "folder": "Partial Occlusion",
        "expected_frames": 25,
    },
    {
        "id": "03_rapid_movement",
        "display_name": "3. Unpredictable Child Movement",
        "folder": "Unpredictable Child Movement",
        "expected_frames": 25,
    },
    {
        "id": "04_overcast",
        "display_name": "4. Overcast / Diffused Lighting",
        "folder": os.path.join("Different Lighting Conditions", "Overcast or Diffused Lighting"),
        "expected_frames": 15,
    },
    {
        "id": "05_daylight",
        "display_name": "5. Normal Daylight",
        "folder": os.path.join("Different Lighting Conditions", "Normal Daylight"),
        "expected_frames": 15,
    },
    {
        "id": "06_glare",
        "display_name": "6. Morning Glare (Lens Flare)",
        "folder": os.path.join("Different Lighting Conditions", "Morning Glare"),
        "expected_frames": 15,
    },
    {
        "id": "07_shadows",
        "display_name": "7. Strong Shadows (High Contrast)",
        "folder": os.path.join("Different Lighting Conditions", "Strong Shadows"),
        "expected_frames": 15,
    },
]


def bbox_iou(box1, box2):
    """Compute IoU between two (x1, y1, x2, y2) bounding boxes."""
    ix1 = max(box1[0], box2[0])
    iy1 = max(box1[1], box2[1])
    ix2 = min(box1[2], box2[2])
    iy2 = min(box1[3], box2[3])

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0

    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0.0 else 0.0


def evaluate_detections(gt_boxes, pred_boxes_with_conf, iou_thresh=0.50):
    """
    Greedy Hungarian-style matching between predictions and ground-truth boxes.
    gt_boxes: list of (x1, y1, x2, y2)
    pred_boxes_with_conf: list of ((x1, y1, x2, y2), conf), sorted descending by conf
    Returns: tp, fp, fn
    """
    matched_gt = set()
    tp = 0
    fp = 0

    for pred_box, conf in pred_boxes_with_conf:
        best_iou = 0.0
        best_gt_idx = -1

        for gt_idx, gt_box in enumerate(gt_boxes):
            if gt_idx in matched_gt:
                continue
            iou = bbox_iou(pred_box, gt_box)
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = gt_idx

        if best_iou >= iou_thresh and best_gt_idx >= 0:
            tp += 1
            matched_gt.add(best_gt_idx)
        else:
            fp += 1

    fn = len(gt_boxes) - len(matched_gt)
    return tp, fp, fn


def load_category_data(cat_folder):
    """Load images and matching ground-truth annotations from the category folder."""
    target_dir = DATASET_BASE / cat_folder
    zip_path = target_dir / "Annotations Export.zip"

    if not zip_path.exists():
        raise FileNotFoundError(f"Missing Annotations Export.zip in {target_dir}")

    # Read all labels from zip into a dict mapping sanitized stem -> list of (cls_id, x1, y1, x2, y2)
    label_dict = {}
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            if name.startswith("labels/") and name.endswith(".txt"):
                fname = os.path.basename(name)
                # Remove prefix hash (e.g., '00045c0b-frame_05062.txt' -> 'frame_05062')
                core_name = fname.split("-", 1)[-1] if "-" in fname else fname
                core_stem = os.path.splitext(core_name)[0]
                lines = z.read(name).decode("utf-8").strip().splitlines()
                boxes = []
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        cls_id = int(parts[0])
                        xc = float(parts[1])
                        yc = float(parts[2])
                        w = float(parts[3])
                        h = float(parts[4])
                        boxes.append((cls_id, xc, yc, w, h))
                label_dict[core_stem] = boxes

    # Find images
    image_files = sorted([
        f for f in os.listdir(target_dir)
        if f.lower().endswith((".jpg", ".png", ".jpeg"))
    ])

    items = []
    for img_name in image_files:
        stem = os.path.splitext(img_name)[0]
        stem_sanitized = stem.replace(" ", "_")

        matched_boxes = None
        if stem in label_dict:
            matched_boxes = label_dict[stem]
        elif stem_sanitized in label_dict:
            matched_boxes = label_dict[stem_sanitized]
        else:
            # Fallback substring match
            for k, v in label_dict.items():
                if k.endswith(stem) or k.endswith(stem_sanitized) or stem in k or stem_sanitized in k:
                    matched_boxes = v
                    break

        if matched_boxes is None:
            print(f"[!] Warning: No label match found for {img_name} in {cat_folder}")
            matched_boxes = []

        items.append({
            "image_path": str(target_dir / img_name),
            "image_name": img_name,
            "raw_gt": matched_boxes,
        })

    return items


def main():
    print("=" * 80)
    print("   CAPSTONE CHAPTER 4: OPERATIONAL CONDITION-BASED EVALUATION")
    print("=" * 80)
    print(f"Model Checkpoint : {MODEL_PATH}")
    print(f"Evaluation Pool  : {DATASET_BASE}")
    print(f"Classes Defined  : 0 = adult, 1 = child (Canonical Truth)")
    print(f"Matching Rule    : Greedy IoU >= 0.50")
    print(f"Operational Conf : 0.65 (LIVE_CHILD_CONF) and 0.50 (Baseline VOC)")
    print("-" * 80)

    if not MODEL_PATH.exists():
        print(f"[ERROR] Model weights not found at: {MODEL_PATH}")
        sys.exit(1)

    model = YOLO(str(MODEL_PATH))

    # Evaluate at both 0.65 (Operational) and 0.50 (Baseline)
    conf_thresholds = [0.65, 0.50]
    all_eval_results = {}

    for target_conf in conf_thresholds:
        mode_label = "OPERATIONAL (conf=0.65)" if target_conf == 0.65 else "BASELINE (conf=0.50)"
        print(f"\n>>> Running Evaluation Mode: {mode_label} <<<")
        print(f"{'Condition Category':<38} | {'Frames':<6} | {'GT Child':<8} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'Precision':<9} | {'Recall':<8} | {'F1-Score':<8}")
        print("-" * 105)

        category_summaries = []
        tot_frames = 0
        tot_gt_child = 0
        tot_tp = 0
        tot_fp = 0
        tot_fn = 0

        tot_gt_adult = 0
        tot_adult_tp = 0
        tot_adult_fp = 0
        tot_adult_fn = 0

        for cat in CATEGORIES:
            items = load_category_data(cat["folder"])
            cat_frames = len(items)
            cat_gt_child = 0
            cat_tp = 0
            cat_fp = 0
            cat_fn = 0

            cat_gt_adult = 0
            cat_adult_tp = 0
            cat_adult_fp = 0
            cat_adult_fn = 0

            for item in items:
                img_bgr = cv2.imread(item["image_path"])
                if img_bgr is None:
                    continue
                img_h, img_w = img_bgr.shape[:2]

                # Convert normalized GT boxes to absolute pixels
                gt_children = []
                gt_adults = []
                for cls_id, xc, yc, w, h in item["raw_gt"]:
                    x1 = (xc - w / 2.0) * img_w
                    y1 = (yc - h / 2.0) * img_h
                    x2 = (xc + w / 2.0) * img_w
                    y2 = (yc + h / 2.0) * img_h
                    box = (x1, y1, x2, y2)
                    if cls_id == 1:
                        gt_children.append(box)
                    elif cls_id == 0:
                        gt_adults.append(box)

                cat_gt_child += len(gt_children)
                cat_gt_adult += len(gt_adults)

                # Predict with model
                results = model.predict(img_bgr, conf=target_conf, imgsz=640, verbose=False, device="cpu")
                r = results[0]

                pred_children = []
                pred_adults = []

                if r.boxes is not None and len(r.boxes) > 0:
                    xyxy = r.boxes.xyxy.cpu().numpy()
                    confs = r.boxes.conf.cpu().numpy()
                    clss = r.boxes.cls.cpu().numpy().astype(int)

                    for box, conf, cls_k in zip(xyxy, confs, clss):
                        b_tuple = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
                        if cls_k == 1:
                            pred_children.append((b_tuple, float(conf)))
                        elif cls_k == 0:
                            pred_adults.append((b_tuple, float(conf)))

                # Sort predictions descending by confidence
                pred_children.sort(key=lambda x: x[1], reverse=True)
                pred_adults.sort(key=lambda x: x[1], reverse=True)

                # Match children
                c_tp, c_fp, c_fn = evaluate_detections(gt_children, pred_children, iou_thresh=0.50)
                cat_tp += c_tp
                cat_fp += c_fp
                cat_fn += c_fn

                # Match adults
                a_tp, a_fp, a_fn = evaluate_detections(gt_adults, pred_adults, iou_thresh=0.50)
                cat_adult_tp += a_tp
                cat_adult_fp += a_fp
                cat_adult_fn += a_fn

            # Category metrics
            prec = (cat_tp / (cat_tp + cat_fp) * 100.0) if (cat_tp + cat_fp) > 0 else 0.0
            rec = (cat_tp / (cat_tp + cat_fn) * 100.0) if (cat_tp + cat_fn) > 0 else 0.0
            f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

            cat_summary = {
                "id": cat["id"],
                "display_name": cat["display_name"],
                "frames": cat_frames,
                "gt_child_instances": cat_gt_child,
                "gt_adult_instances": cat_gt_adult,
                "tp": cat_tp,
                "fp": cat_fp,
                "fn": cat_fn,
                "precision": round(prec, 2),
                "recall": round(rec, 2),
                "f1_score": round(f1, 2),
            }
            category_summaries.append(cat_summary)

            print(f"{cat['display_name']:<38} | {cat_frames:<6} | {cat_gt_child:<8} | {cat_tp:<4} | {cat_fp:<4} | {cat_fn:<4} | {prec:>7.2f}% | {rec:>6.2f}% | {f1:>6.2f}%")

            tot_frames += cat_frames
            tot_gt_child += cat_gt_child
            tot_tp += cat_tp
            tot_fp += cat_fp
            tot_fn += cat_fn

            tot_gt_adult += cat_gt_adult
            tot_adult_tp += cat_adult_tp
            tot_adult_fp += cat_adult_fp
            tot_adult_fn += cat_adult_fn

        # Overall composite
        tot_prec = (tot_tp / (tot_tp + tot_fp) * 100.0) if (tot_tp + tot_fp) > 0 else 0.0
        tot_rec = (tot_tp / (tot_tp + tot_fn) * 100.0) if (tot_tp + tot_fn) > 0 else 0.0
        tot_f1 = (2 * tot_prec * tot_rec / (tot_prec + tot_rec)) if (tot_prec + tot_rec) > 0 else 0.0

        print("-" * 105)
        print(f"{'OVERALL OPERATIONAL COMPOSITE':<38} | {tot_frames:<6} | {tot_gt_child:<8} | {tot_tp:<4} | {tot_fp:<4} | {tot_fn:<4} | {tot_prec:>7.2f}% | {tot_rec:>6.2f}% | {tot_f1:>6.2f}%")
        print("=" * 105)

        all_eval_results[f"conf_{target_conf}"] = {
            "confidence_threshold": target_conf,
            "mode": mode_label,
            "total_frames": tot_frames,
            "total_gt_child_instances": tot_gt_child,
            "total_gt_adult_instances": tot_gt_adult,
            "composite": {
                "tp": tot_tp,
                "fp": tot_fp,
                "fn": tot_fn,
                "precision": round(tot_prec, 2),
                "recall": round(tot_rec, 2),
                "f1_score": round(tot_f1, 2),
            },
            "by_category": category_summaries,
        }

    # Save artifact
    payload = {
        "evaluation_timestamp": datetime.datetime.now().isoformat(),
        "model_checkpoint": str(MODEL_PATH.name),
        "source_dataset": str(DATASET_BASE),
        "evaluation_protocol": "Greedy IoU >= 0.50 matching against manual Label Studio ground truth",
        "results": all_eval_results,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n[OK] Complete results exported to: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()

