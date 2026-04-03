# YOLOv8 Merged V1 Model — Post-Training Analysis

## Final Metrics (Epoch 50)
| Metric | Value |
|--------|-------|
| mAP50 | **84.8%** |
| mAP50-95 | **59.7%** |
| Precision | 78.6% |
| Recall | 80.7% |

## Confusion Matrix Breakdown

| | Predicted Adult | Predicted Child | Missed (Background) |
|---|---|---|---|
| **True Adult** | ✅ 323 | ❌ 22 misclassified as child | ❌ 26 missed entirely |
| **True Child** | ❌ 43 misclassified as adult | ✅ 139 | ❌ 23 missed entirely |
| **Background** | ❌ 74 false positives (adult) | ❌ 70 false positives (child) | — |

---

## Issue 1: Duplicate / Overlapping Labels on the Same Person

**What you're seeing:** A single person gets 2–3 bounding boxes stacked on top of each other (e.g., "adult 0.7", "adult 0.9", "adult 0.7" all on one person).

**Root causes:**
1. **NMS IoU threshold too high (0.7).** Non-Maximum Suppression (NMS) is the algorithm that merges overlapping boxes. At `iou=0.7`, YOLO only merges two boxes if they overlap by 70%+. Slightly offset boxes on the same person survive as separate detections.
2. **Batch size of 2 during training.** With only 2 images per batch, the model sees very noisy gradient updates each step. This makes bounding box regression less precise, leading to multiple slightly-offset predictions for the same object.
3. **Possible duplicate annotations in training data.** If some frames in Label Studio accidentally had two overlapping boxes on the same person (common when pre-labels overlap with manual labels), the model literally *learned* to output duplicates.

**Fix:** Lower the NMS IoU threshold during inference from `0.7` → `0.45`. This will aggressively merge overlapping boxes.

---

## Issue 2: Missed Detections (Person Behind Another Person Not Detected)

**Root causes:**
1. **Occluded people are underrepresented in training data.** The confusion matrix shows 26 adults and 23 children were missed entirely (predicted as "background"). The model hasn't seen enough examples of partially hidden people.
2. **Small dataset size.** 844 images is a solid start but still limited. The model learns the "easy" cases well but struggles with edge cases like occlusion.
3. **YOLOv8n (nano) is the smallest model.** It has fewer parameters to learn complex patterns like "there's a second person behind this one."

**Fix:** This requires more training data with occluded pedestrians, and potentially upgrading from `yolov8n` to `yolov8s` (small) for better feature extraction.

---

## Issue 3: High False Positive Rate (144 False Alarms)

**What the matrix shows:** 74 background objects were falsely detected as adults, and 70 as children. That's **144 total false positives**.

**Root cause:** The model is too eager to detect. The confidence threshold during inference is likely set too low (0.3), letting weak, incorrect detections through.

**Fix:** Raise the confidence threshold during inference from `0.3` → `0.5`.

---

## Issue 4: Child ↔ Adult Confusion (65 misclassifications)

**What the matrix shows:** 43 actual children were misclassified as adults, and 22 adults were misclassified as children.

**Root cause:** Class imbalance — there are significantly more adult annotations than child annotations in the dataset. The model defaults to "adult" when uncertain.

**Fix:** Use class weights or oversample child examples during training.

---

## Recommended Fixes (Priority Order)

### Quick Wins (No Retraining Needed)
These are inference-time parameter changes:

```python
results = model.predict(
    source=frame,
    conf=0.5,      # ← Raise from 0.3 to reduce false positives
    iou=0.45,      # ← Lower from 0.7 to eliminate duplicate boxes
    max_det=50     # ← Lower from 300 (you'll never have 300 people)
)
```

### Medium-Term (Retrain with Better Settings)
```python
results = model.train(
    data=dataset_yaml,
    epochs=100,        # ← Double from 50 (curves still improving)
    batch=4,           # ← Try 4 if memory allows (smoother gradients)
    imgsz=640,
    patience=20,       # ← Stop early if no improvement for 20 epochs
    augment=True,      # ← Add augmentation during training
    cos_lr=True,       # ← Cosine learning rate for better convergence
    close_mosaic=20,   # ← Disable mosaic later in training for stability
)
```

### Long-Term (Better Data)
1. **Audit training labels** — Open Label Studio exports and check for duplicate boxes on single persons
2. **Add more child data** — The 43 children misclassified as adults suggests we need more child examples, especially in shadows and at distance
3. **Add occluded examples** — Specifically label frames where people are partially behind each other
4. **Consider upgrading to `yolov8s.pt`** — The "small" model has 3x more parameters than "nano" and handles edge cases better
