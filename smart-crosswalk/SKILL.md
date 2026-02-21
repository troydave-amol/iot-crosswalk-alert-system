---
name: smart-crosswalk
description: |
  Full-stack AI agent skill for the IoT-Based Smart School-Zone Crosswalk Alert System capstone project.
  Use this skill when working on any part of the project including YOLOv8 model training/fine-tuning
  for child pedestrian detection, dataset preparation (CityPersons/JAAD), Flask+MySQL backend,
  Socket.IO live dashboard, analytics range filters, API endpoint validation, ROI trigger logic,
  or report generation. Enforces project scope (visual warning only, no SMS/audio/age
  estimation/face recognition).
---

# Smart Crosswalk Capstone

## Project Identity

**Title**: IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection
**Client**: Traffic Management Center (TMC), Casisang Central School crosswalk, Barangay Casisang, Malaybalay City
**Stack**: YOLOv8 + Flask + MySQL + Socket.IO + HTML/JS dashboard

---

## Non-Negotiable Scope Rules

Before executing ANY task, verify it fits these constraints:

- Detection = "visually classified as children based on body size, proportions, and school-age appearance" (NEVER "detect 13 years old and below")
- Warning output = visual only (LED sign/lightbox/beacon)
- NO SMS, NO audio/sirens/buzzers, NO face recognition, NO speed detection, NO biological age estimation
- Warning ON only when a child-classified pedestrian is inside the Crosswalk ROI; OFF otherwise

If a request breaks scope, stop and ask for clarification or refuse.

---

## 3-Layer Architecture

| Layer | Role | Location |
|---|---|---|
| **Directive** | What to do (SOPs) | `directives/` |
| **Orchestration** | Decision-making (YOU) | — |
| **Execution** | Deterministic scripts | `execution/` |

Always check `execution/` for an existing script before creating a new one.

---

## Workflow Decision Tree

**What are you working on?**

- Dataset / annotations → Follow **Dataset Workflow** below
- Model training / evaluation → Follow **Training Workflow** below
- Backend / API → Follow **Backend Workflow** below
- Dashboard / frontend → Follow **Frontend Workflow** below
- Analytics correctness → Follow **Analytics Validation Workflow** below

---

## Dataset Workflow

1. Identify dataset folder structure under `datasets/`
2. Confirm annotation format (YOLO `.txt` labels or convert)
3. Validate labels with `execution/` scripts (bounds check, missing labels)
4. Update or create `datasets/<name>.yaml` (see `datasets/citypersons.yaml` as reference)
5. Create train/val/test split
6. For child-class fine-tuning: follow annotation guideline — see `references/annotation_guideline.md`

**Active datasets:**
- `datasets/citypersons/` — pedestrian baseline (~8,479 files)
- `datasets/jaad/` — road/crosswalk behavior context (~4,777 files)
- `datasets/crosswalk_child.yaml` — child-class fine-tune config (in progress)

---

## Training Workflow

1. Baseline model: `yolov8n.pt` (present in project root)
2. Existing training run: `runs/detect/train/` — contains weights, curves, confusion matrix
3. For fine-tuning child class: use `datasets/crosswalk_child.yaml`
4. Evaluate: precision/recall/F1 + latency (ms) — must go into manuscript
5. See `references/training_plan.md` for full training parameters and evaluation targets

---

## Backend Workflow

Flask app: `app.py` | DB layer: `db.py`

Key endpoints that must remain stable:

| Endpoint | Contract |
|---|---|
| `GET /api/events` | range filter, pagination (total+rows), 503 on DB error |
| `GET /api/analytics` | SQL-accurate aggregates, includes metadata |
| `GET /api/health` | returns `{"ok": true}` even if DB is down |

See `references/api_contract.md` for full field definitions and range rules.

**Self-anneal loop for backend bugs:**
1. Reproduce with minimal steps
2. Identify root cause (logs/SQL/network proof)
3. Fix deterministically
4. Add regression test in `execution/`
5. Update relevant directive

---

## Frontend Workflow

Dashboard pages: Live View, Logs, Analytics, Reports, Settings
Entry: `templates/index.html` | Styles/JS: `static/`

**Range filter rules (must always hold):**
- 15m ⊆ 1h ⊆ today ⊆ all
- Totals must satisfy nested subsets for events/warnings/detections
- All pages fetch from `/api/events` — NO session-log fallback

---

## Analytics Validation Workflow

When analytics numbers look wrong:
1. Run raw SQL on MySQL to get ground truth
2. Compare to `/api/analytics` or `/api/events` response for same range
3. Compare API response to dashboard KPI display
4. If any mismatch → treat as bug until proven otherwise

**Canonical field names** (use these everywhere):

```
timestamp_iso, warning_device_on, child_in_roi, confidence, latency_ms, scenario (optional)
```

Legacy field `warning_on` is fallback only.

---

## Resources

- `references/api_contract.md` — Full API field specs and range rules
- `references/annotation_guideline.md` — Child-class labeling rules (inclusion/exclusion, bbox, occlusion)
- `references/training_plan.md` — YOLOv8 training parameters and evaluation targets
- `scripts/` — Execution scripts (dataset validation, API smoke tests, DB queries)
