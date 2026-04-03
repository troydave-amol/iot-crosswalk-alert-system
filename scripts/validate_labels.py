"""
Validate YOLO-format label files for a manual dataset under datasets/.

Usage:
    python scripts/validate_labels.py --dataset site_dataset_v1
    python scripts/validate_labels.py --dataset site_dataset_v1 --images-subdir annotation_exports/yolo/images --labels-subdir annotation_exports/yolo/labels

Outputs:
    reports/<dataset>_label_validation.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
REPORTS_DIR = PROJECT_ROOT / "reports"


def validate_dataset(
    dataset_name: str,
    images_subdir: str = "selected_frames",
    labels_subdir: str = "labels",
) -> list[dict]:
    dataset_path = Path(dataset_name)
    if dataset_path.is_absolute():
        raise ValueError("--dataset must be a path relative to datasets/")

    dataset_dir = DATASETS_DIR / dataset_path
    images_dir = dataset_dir / images_subdir
    labels_dir = dataset_dir / labels_subdir

    if not images_dir.exists():
        raise FileNotFoundError(f"images directory not found: {images_dir}")
    if not labels_dir.exists():
        raise FileNotFoundError(f"labels directory not found: {labels_dir}")

    image_exts = {".jpg", ".jpeg", ".png", ".bmp"}
    issues = []

    image_files = [f for f in images_dir.rglob("*") if f.suffix.lower() in image_exts]

    for img_path in image_files:
        rel = img_path.relative_to(images_dir)
        label_path = labels_dir / rel.with_suffix(".txt")

        if not label_path.exists():
            issues.append(
                {
                    "image": str(img_path.relative_to(PROJECT_ROOT)),
                    "label": str(label_path.relative_to(PROJECT_ROOT)),
                    "issue": "missing_label_file",
                    "line": "",
                    "detail": "No corresponding .txt label file found",
                }
            )
            continue

        lines = label_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            issues.append(
                {
                    "image": str(img_path.relative_to(PROJECT_ROOT)),
                    "label": str(label_path.relative_to(PROJECT_ROOT)),
                    "issue": "empty_label_file",
                    "line": "",
                    "detail": "Label file exists but is empty",
                }
            )
            continue

        for lineno, raw in enumerate(lines, start=1):
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split()
            if len(parts) != 5:
                issues.append(
                    {
                        "image": str(img_path.relative_to(PROJECT_ROOT)),
                        "label": str(label_path.relative_to(PROJECT_ROOT)),
                        "issue": "malformed_line",
                        "line": lineno,
                        "detail": f"Expected 5 values, got {len(parts)}: {raw!r}",
                    }
                )
                continue

            try:
                int(parts[0])
                cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except ValueError:
                issues.append(
                    {
                        "image": str(img_path.relative_to(PROJECT_ROOT)),
                        "label": str(label_path.relative_to(PROJECT_ROOT)),
                        "issue": "parse_error",
                        "line": lineno,
                        "detail": f"Cannot parse values: {raw!r}",
                    }
                )
                continue

            for name, value in (("cx", cx), ("cy", cy), ("w", w), ("h", h)):
                if not (0.0 <= value <= 1.0):
                    issues.append(
                        {
                            "image": str(img_path.relative_to(PROJECT_ROOT)),
                            "label": str(label_path.relative_to(PROJECT_ROOT)),
                            "issue": "out_of_bounds",
                            "line": lineno,
                            "detail": f"{name}={value:.4f} is outside [0, 1]",
                        }
                    )

    return issues


def save_report(issues: list[dict], dataset_name: str) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    dataset_slug = "_".join(Path(dataset_name).parts)
    out_path = REPORTS_DIR / f"{dataset_slug}_label_validation.csv"
    fieldnames = ["image", "label", "issue", "line", "detail"]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(issues)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate YOLO label files.")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset path under datasets/, for example site_dataset_v1",
    )
    parser.add_argument(
        "--images-subdir",
        default="selected_frames",
        help="Image folder inside the dataset root (default: selected_frames)",
    )
    parser.add_argument(
        "--labels-subdir",
        default="labels",
        help="Label folder inside the dataset root (default: labels)",
    )
    args = parser.parse_args()

    print(f"Validating dataset: {args.dataset}")
    issues = validate_dataset(
        args.dataset,
        images_subdir=args.images_subdir,
        labels_subdir=args.labels_subdir,
    )

    if not issues:
        print("[OK] No issues found.")
        return

    report_path = save_report(issues, args.dataset)
    by_type: dict[str, int] = {}
    for issue in issues:
        by_type[issue["issue"]] = by_type.get(issue["issue"], 0) + 1

    print(f"[WARN] {len(issues)} issue(s) found:")
    for issue_type, count in sorted(by_type.items()):
        print(f"   {issue_type}: {count}")
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
