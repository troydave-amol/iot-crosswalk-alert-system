"""
execution/split_dataset.py
--------------------------
Splits a flat YOLO dataset (images/ + labels/) into train/val/test sub-splits.

Usage:
    python execution/split_dataset.py --dataset citypersons --split 80 10 10
    python execution/split_dataset.py --dataset jaad --split 80 10 10

Inputs:
    datasets/<name>/images/   — flat directory of images
    datasets/<name>/labels/   — flat directory of .txt labels

Outputs:
    datasets/<name>/images/train/  val/  test/
    datasets/<name>/labels/train/  val/  test/

Notes:
    - Only images WITH a corresponding label are included in the split.
    - Existing sub-split directories will raise an error (use --force to overwrite).
    - Shuffle is seeded (seed=42) for reproducibility.
"""

import argparse
import random
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
SEED = 42


def split_dataset(dataset_name: str, ratios: tuple[float, float, float], force: bool = False):
    train_r, val_r, test_r = ratios
    assert abs(train_r + val_r + test_r - 1.0) < 1e-6, "Ratios must sum to 1.0"

    dataset_dir = DATASETS_DIR / dataset_name
    images_dir  = dataset_dir / "images"
    labels_dir  = dataset_dir / "labels"

    # Guard against splitting an already-split dataset
    for split in ("train", "val", "test"):
        if (images_dir / split).exists() and not force:
            raise RuntimeError(
                f"Sub-split '{split}' already exists in {images_dir}. "
                f"Use --force to re-split (WARNING: this will move files again)."
            )

    # Collect paired (image, label) paths from flat directories only
    pairs: list[tuple[Path, Path]] = []
    for img_path in sorted(images_dir.iterdir()):
        if img_path.is_dir():
            continue  # skip existing sub-splits
        if img_path.suffix.lower() not in IMAGE_EXTS:
            continue
        lbl_path = labels_dir / img_path.with_suffix(".txt").name
        if lbl_path.exists():
            pairs.append((img_path, lbl_path))
        else:
            print(f"  ⚠️  Skipping (no label): {img_path.name}")

    if not pairs:
        raise ValueError(f"No paired image+label files found in {dataset_dir}")

    # Reproducible shuffle
    random.seed(SEED)
    random.shuffle(pairs)

    n = len(pairs)
    n_train = int(n * train_r)
    n_val   = int(n * val_r)

    splits = {
        "train": pairs[:n_train],
        "val":   pairs[n_train:n_train + n_val],
        "test":  pairs[n_train + n_val:],
    }

    for split_name, split_pairs in splits.items():
        (images_dir / split_name).mkdir(exist_ok=True)
        (labels_dir / split_name).mkdir(exist_ok=True)
        for img_path, lbl_path in split_pairs:
            shutil.move(str(img_path), str(images_dir / split_name / img_path.name))
            shutil.move(str(lbl_path), str(labels_dir / split_name / lbl_path.name))
        print(f"  {split_name}: {len(split_pairs)} pairs")

    print(f"✅ Split complete — total {n} pairs → train:{len(splits['train'])} val:{len(splits['val'])} test:{len(splits['test'])}")
    print(f"   Remember to update datasets/{dataset_name}.yaml with the new paths.")


def main():
    parser = argparse.ArgumentParser(description="Split a YOLO dataset into train/val/test.")
    parser.add_argument("--dataset", required=True,  help="Dataset name under datasets/")
    parser.add_argument("--split",   nargs=3, type=int, default=[80, 10, 10],
                        metavar=("TRAIN", "VAL", "TEST"),
                        help="Split percentages (must sum to 100, default: 80 10 10)")
    parser.add_argument("--force",   action="store_true",
                        help="Allow re-splitting even if sub-splits already exist")
    args = parser.parse_args()

    total = sum(args.split)
    if total != 100:
        raise ValueError(f"Split percentages must sum to 100, got {total}")

    ratios = tuple(v / 100.0 for v in args.split)
    print(f"Splitting '{args.dataset}' with ratios train={args.split[0]}% val={args.split[1]}% test={args.split[2]}%")
    split_dataset(args.dataset, ratios, force=args.force)


if __name__ == "__main__":
    main()
