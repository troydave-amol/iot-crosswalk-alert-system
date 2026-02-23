"""
scripts/validate_labels.py
----------------------------
Validates YOLO-format label files for a given dataset under datasets/.

Usage:
    python scripts/validate_labels.py --dataset citypersons
    python scripts/validate_labels.py --dataset jaad

Outputs:
    reports/<dataset>_label_validation.csv   — one row per issue found
    Console summary of totals
"""

import argparse
import csv
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
REPORTS_DIR  = PROJECT_ROOT / "reports"


def validate_dataset(dataset_name: str) -> list[dict]:
    """
    Walk images/ and labels/ for the given dataset.
    Returns a list of issue dicts.
    """
    dataset_dir = DATASETS_DIR / dataset_name
    images_dir  = dataset_dir / "images"
    labels_dir  = dataset_dir / "labels"

    if not images_dir.exists():
        raise FileNotFoundError(f"images/ not found: {images_dir}")
    if not labels_dir.exists():
        raise FileNotFoundError(f"labels/ not found: {labels_dir}")

    image_exts = {".jpg", ".jpeg", ".png", ".bmp"}
    issues = []

    image_files = [f for f in images_dir.rglob("*") if f.suffix.lower() in image_exts]

    for img_path in image_files:
        # Derive expected label path (same relative structure, .txt extension)
        rel = img_path.relative_to(images_dir)
        label_path = labels_dir / rel.with_suffix(".txt")

        # -- Missing label file --
        if not label_path.exists():
            issues.append({
                "image": str(img_path.relative_to(PROJECT_ROOT)),
                "label": str(label_path.relative_to(PROJECT_ROOT)),
                "issue": "missing_label_file",
                "line":  "",
                "detail": "No corresponding .txt label file found",
            })
            continue

        # -- Parse label file --
        with open(label_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            issues.append({
                "image":  str(img_path.relative_to(PROJECT_ROOT)),
                "label":  str(label_path.relative_to(PROJECT_ROOT)),
                "issue":  "empty_label_file",
                "line":   "",
                "detail": "Label file exists but is empty",
            })
            continue

        for lineno, raw in enumerate(lines, start=1):
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            if len(parts) != 5:
                issues.append({
                    "image":  str(img_path.relative_to(PROJECT_ROOT)),
                    "label":  str(label_path.relative_to(PROJECT_ROOT)),
                    "issue":  "malformed_line",
                    "line":   lineno,
                    "detail": f"Expected 5 values, got {len(parts)}: {raw!r}",
                })
                continue

            try:
                cls, cx, cy, w, h = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                issues.append({
                    "image":  str(img_path.relative_to(PROJECT_ROOT)),
                    "label":  str(label_path.relative_to(PROJECT_ROOT)),
                    "issue":  "parse_error",
                    "line":   lineno,
                    "detail": f"Cannot parse values: {raw!r}",
                })
                continue

            # -- Out-of-bounds check --
            for name, val in [("cx", cx), ("cy", cy), ("w", w), ("h", h)]:
                if not (0.0 <= val <= 1.0):
                    issues.append({
                        "image":  str(img_path.relative_to(PROJECT_ROOT)),
                        "label":  str(label_path.relative_to(PROJECT_ROOT)),
                        "issue":  "out_of_bounds",
                        "line":   lineno,
                        "detail": f"{name}={val:.4f} is outside [0, 1]",
                    })

    return issues


def save_report(issues: list[dict], dataset_name: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / f"{dataset_name}_label_validation.csv"
    fieldnames = ["image", "label", "issue", "line", "detail"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(issues)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Validate YOLO label files.")
    parser.add_argument("--dataset", required=True, help="Dataset name under datasets/")
    args = parser.parse_args()

    print(f"Validating dataset: {args.dataset}")
    issues = validate_dataset(args.dataset)

    if not issues:
        print("✅ No issues found.")
    else:
        report_path = save_report(issues, args.dataset)
        by_type: dict[str, int] = {}
        for issue in issues:
            by_type[issue["issue"]] = by_type.get(issue["issue"], 0) + 1
        print(f"⚠️  {len(issues)} issue(s) found:")
        for k, v in sorted(by_type.items()):
            print(f"   {k}: {v}")
        print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
