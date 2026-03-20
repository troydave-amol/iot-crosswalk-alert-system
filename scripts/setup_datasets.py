"""
Scaffold the manual crosswalk dataset workspace.

The active dataset layout is centered on footage collected by the team at the
deployment site. This script creates the standard folder structure and writes a
starter YOLO config under exports/yolo/.
"""

from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
DEFAULT_DATASET = "site_dataset_v1"

DATASET_SUBDIRS = {
    "videos_raw": "Original site recordings from the crosswalk camera.",
    "frames_raw": "All extracted frames before quality review.",
    "frames_selected": "Frames approved for annotation and export.",
    "labels": "YOLO txt labels matching frames_selected/.",
    "exports": "Generated train/val/test datasets for training.",
    "rejected": "Blurred, duplicate, off-angle, or unusable frames.",
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_yaml(export_root: Path) -> str:
    lines = [
        "# Manual crosswalk dataset exported from site_dataset_v1.",
        "# Refresh this file after you generate a new train/val/test split.",
        f"path: {export_root.as_posix()}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "",
        "names:",
        "  0: child_like",
        "  1: adult_like",
        "",
    ]
    return "\n".join(lines)


def build_readme(dataset_root: Path) -> str:
    lines = [
        f"# {dataset_root.name}",
        "",
        "Manual dataset workspace for the smart crosswalk capstone.",
        "",
    ]
    for name, description in DATASET_SUBDIRS.items():
        lines.append(f"- `{name}/` - {description}")
    lines.extend(
        [
            "",
            "Recommended sequence:",
            "1. Save raw recordings in `videos_raw/`.",
            "2. Extract frames into `frames_raw/`.",
            "3. Move approved frames into `frames_selected/`.",
            "4. Create YOLO labels in `labels/`.",
            "5. Run `python scripts/validate_labels.py --dataset site_dataset_v1`.",
            "6. Run `python scripts/split_dataset.py --dataset site_dataset_v1`.",
        ]
    )
    return "\n".join(lines) + "\n"


def ensure_layout(dataset_name: str) -> tuple[Path, Path]:
    dataset_root = DATASETS_DIR / dataset_name
    export_root = dataset_root / "exports" / "yolo"

    ensure_dir(dataset_root)
    for name in DATASET_SUBDIRS:
        ensure_dir(dataset_root / name)

    for split in ("train", "val", "test"):
        ensure_dir(export_root / "images" / split)
        ensure_dir(export_root / "labels" / split)

    (dataset_root / "README.md").write_text(
        build_readme(dataset_root),
        encoding="utf-8",
    )
    (export_root / "data.yaml").write_text(
        build_yaml(export_root),
        encoding="utf-8",
    )
    return dataset_root, export_root


def print_summary(dataset_root: Path, export_root: Path) -> None:
    print("=" * 60)
    print("MANUAL DATASET WORKSPACE")
    print("=" * 60)
    print(f"dataset root : {dataset_root}")
    print(f"export root  : {export_root}")
    print()
    for name, description in DATASET_SUBDIRS.items():
        print(f"- {name:<15} {dataset_root / name}")
        print(f"  {description}")
    print()
    print(f"Starter YOLO config: {export_root / 'data.yaml'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scaffold the manual crosswalk dataset workspace."
    )
    parser.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET,
        help=f"Folder name to create under datasets/ (default: {DEFAULT_DATASET})",
    )
    args = parser.parse_args()

    dataset_root, export_root = ensure_layout(args.dataset_name)
    print("Workspace scaffold refreshed.")
    print_summary(dataset_root, export_root)


if __name__ == "__main__":
    main()
