"""
Export a manual dataset into YOLO train/val/test folders.

Usage:
    python scripts/split_dataset.py --dataset site_dataset_v1
    python scripts/split_dataset.py --dataset site_dataset_v1 --split 70 15 15 --force

Source folders:
    datasets/<dataset>/selected_frames/
    datasets/<dataset>/labels/

Output folders:
    datasets/<dataset>/annotation_exports/yolo/images/train|val|test/
    datasets/<dataset>/annotation_exports/yolo/labels/train|val|test/
"""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
SEED = 42


def _build_yaml(export_root: Path) -> str:
    lines = [
        "# Manual crosswalk dataset export",
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


def _iter_pairs(images_dir: Path, labels_dir: Path) -> list[tuple[Path, Path, Path]]:
    pairs: list[tuple[Path, Path, Path]] = []
    for img_path in sorted(images_dir.rglob("*")):
        if img_path.is_dir() or img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        rel = img_path.relative_to(images_dir)
        lbl_path = labels_dir / rel.with_suffix(".txt")
        if lbl_path.exists():
            pairs.append((img_path, lbl_path, rel))
        else:
            print(f"  [WARN] Skipping (no label): {rel.as_posix()}")
    return pairs


def _prepare_output(export_root: Path, force: bool) -> None:
    images_root = export_root / "images"
    labels_root = export_root / "labels"

    if force:
        for path in (images_root, labels_root):
            if path.exists():
                shutil.rmtree(path)

    for split in ("train", "val", "test"):
        target_img = images_root / split
        target_lbl = labels_root / split
        if (target_img.exists() or target_lbl.exists()) and not force:
            raise RuntimeError(
                f"Export split folders already exist in {export_root}. "
                "Use --force to rebuild them."
            )
        target_img.mkdir(parents=True, exist_ok=True)
        target_lbl.mkdir(parents=True, exist_ok=True)


def export_split_dataset(
    dataset_name: str,
    ratios: tuple[float, float, float],
    force: bool = False,
    images_subdir: str = "selected_frames",
    labels_subdir: str = "labels",
    output_root: str = "annotation_exports/yolo",
) -> None:
    train_r, val_r, test_r = ratios
    assert abs(train_r + val_r + test_r - 1.0) < 1e-6, "Ratios must sum to 1.0"

    dataset_dir = DATASETS_DIR / Path(dataset_name)
    images_dir = dataset_dir / images_subdir
    labels_dir = dataset_dir / labels_subdir
    export_root = dataset_dir / output_root

    if not images_dir.exists():
        raise FileNotFoundError(f"selected_frames directory not found: {images_dir}")
    if not labels_dir.exists():
        raise FileNotFoundError(f"labels directory not found: {labels_dir}")

    pairs = _iter_pairs(images_dir, labels_dir)
    if not pairs:
        raise ValueError(f"No paired image+label files found in {dataset_dir}")

    _prepare_output(export_root, force=force)

    random.seed(SEED)
    random.shuffle(pairs)

    n = len(pairs)
    n_train = int(n * train_r)
    n_val = int(n * val_r)
    splits = {
        "train": pairs[:n_train],
        "val": pairs[n_train:n_train + n_val],
        "test": pairs[n_train + n_val:],
    }

    for split_name, split_pairs in splits.items():
        for img_path, lbl_path, rel in split_pairs:
            dst_img = export_root / "images" / split_name / rel
            dst_lbl = export_root / "labels" / split_name / rel.with_suffix(".txt")
            dst_img.parent.mkdir(parents=True, exist_ok=True)
            dst_lbl.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img_path, dst_img)
            shutil.copy2(lbl_path, dst_lbl)
        print(f"  {split_name}: {len(split_pairs)} pairs")

    (export_root / "data.yaml").write_text(
        _build_yaml(export_root),
        encoding="utf-8",
    )

    print(
        "[OK] Export complete - "
        f"total {n} pairs -> train:{len(splits['train'])} val:{len(splits['val'])} test:{len(splits['test'])}"
    )
    print(f"   YOLO config refreshed at: {export_root / 'data.yaml'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a manual YOLO dataset into train/val/test folders."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset path under datasets/, for example site_dataset_v1",
    )
    parser.add_argument(
        "--split",
        nargs=3,
        type=int,
        default=[80, 10, 10],
        metavar=("TRAIN", "VAL", "TEST"),
        help="Split percentages (must sum to 100, default: 80 10 10)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete the existing annotation_exports/yolo split folders before rebuilding them",
    )
    parser.add_argument(
        "--images-subdir",
        default="selected_frames",
        help="Image source folder inside the dataset root (default: selected_frames)",
    )
    parser.add_argument(
        "--labels-subdir",
        default="labels",
        help="Label source folder inside the dataset root (default: labels)",
    )
    parser.add_argument(
        "--output-root",
        default="annotation_exports/yolo",
        help="Export folder inside the dataset root (default: annotation_exports/yolo)",
    )
    args = parser.parse_args()

    total = sum(args.split)
    if total != 100:
        raise ValueError(f"Split percentages must sum to 100, got {total}")

    ratios = tuple(v / 100.0 for v in args.split)
    print(
        f"Exporting '{args.dataset}' with ratios "
        f"train={args.split[0]}% val={args.split[1]}% test={args.split[2]}%"
    )
    export_split_dataset(
        args.dataset,
        ratios,
        force=args.force,
        images_subdir=args.images_subdir,
        labels_subdir=args.labels_subdir,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    main()
