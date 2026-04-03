import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
YOLO_ROOT = PROJECT_ROOT / "datasets" / "merged_dataset_v2" / "training_runs" / "colab_train_merged_v2"
FINAL_MODEL_DIR = PROJECT_ROOT / "datasets" / "merged_dataset_v2" / "trained_model"

FILE_MAP = {
    "weights/best.pt": "weights/best.pt",
    "weights/last.pt": "weights/last.pt",
    "args.yaml": "training_args.yaml",
    "results.png": "metrics/training_metrics_overview.png",
    "results.csv": "metrics/training_metrics.csv",
    "confusion_matrix.png": "metrics/confusion_matrix.png",
    "confusion_matrix_normalized.png": "metrics/confusion_matrix_normalized.png",
    "BoxF1_curve.png": "metrics/box_f1_curve.png",
    "BoxPR_curve.png": "metrics/box_pr_curve.png",
    "BoxP_curve.png": "metrics/box_precision_curve.png",
    "BoxR_curve.png": "metrics/box_recall_curve.png",
    "labels.jpg": "metrics/label_distribution.png",
}


def _resolve_run_dir() -> Path | None:
    if YOLO_ROOT.exists():
        return YOLO_ROOT

    candidates = sorted(
        PROJECT_ROOT.glob("datasets/merged_dataset_v2/training_runs/*"),
        key=lambda path: path.name.lower(),
    )
    return candidates[0] if candidates else None


def _copy_if_exists(run_dir: Path, source_rel: str, target_rel: str) -> int:
    source = run_dir / source_rel
    if not source.exists():
        return 0

    target = FINAL_MODEL_DIR / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f"Copied: {source_rel} -> {target_rel}")
    return 1


def humanize_runs():
    print("--- Organizing YOLOv8 Trained Model ---\n")
    run_dir = _resolve_run_dir()
    if not run_dir:
        print("Could not locate a completed training run under datasets/merged_dataset_v2/training_runs/.")
        return

    FINAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0

    for source_rel, target_rel in FILE_MAP.items():
        copied += _copy_if_exists(run_dir, source_rel, target_rel)

    for train_image in sorted(run_dir.glob("train_batch*.jpg")):
        batch_id = re.sub(r"\D+", "", train_image.stem)
        copied += _copy_if_exists(
            run_dir,
            train_image.name,
            f"training_previews/train_batch_{batch_id}.jpg",
        )

    for val_image in sorted(run_dir.glob("val_batch*.jpg")):
        match = re.match(r"val_batch(\d+)_(labels|pred)", val_image.stem)
        if not match:
            continue
        batch_id, image_type = match.groups()
        suffix = "ground_truth" if image_type == "labels" else "prediction"
        copied += _copy_if_exists(
            run_dir,
            val_image.name,
            f"validation_previews/validation_batch_{batch_id}_{suffix}.jpg",
        )

    training_runs_root = PROJECT_ROOT / "datasets" / "merged_dataset_v2" / "training_runs"
    if training_runs_root.exists() and training_runs_root.is_dir():
        print(f"\nCleaning up processed training runs: {training_runs_root}")
        shutil.rmtree(training_runs_root)

    print(f"\n{'=' * 50}")
    print(f"Copied {copied} organized artifact(s) into:")
    print(FINAL_MODEL_DIR)
    print(f"{'=' * 50}")

if __name__ == "__main__":
    humanize_runs()
