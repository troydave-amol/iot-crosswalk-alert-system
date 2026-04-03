from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
DATASETS_DIR = PROJECT_ROOT / "datasets"

ROOT_RENAMES = {
    "afternoon_v1": "source_afternoon_v1",
    "afternoon_v2": "source_afternoon_v2",
    "morning_v1": "source_morning_v1",
    "merged_v1": "merged_dataset_v1",
    "merged_v2": "merged_dataset_v2",
}

SUBDIR_RENAMES = {
    "exports": "annotation_exports",
    "frames_selected": "selected_frames",
    "frames_raw": "raw_frames",
    "model_weights": "weights",
    "performance_graphs": "metrics",
}

YAML_NAMES = ["adult", "child"]

MORNING_RE = re.compile(
    r"^(?:Morning_)?(?P<ip>\d+\.\d+\.\d+\.\d+)_(?P<camera>\d+)_(?P<clip>\d+)_(?P<segment>\d+)"
    r"(?:_dense_(?P<dense>[\d.]+)s|_(?P<frame>\d+))$",
    re.IGNORECASE,
)
AFTERNOON_V1_FRAME_RE = re.compile(
    r"^(?:Afternoon_)?aft_(?P<start>\d+)_(?P<end>\d+)_(?P<camera>\d+)_(?P<frame>\d+)$",
    re.IGNORECASE,
)
AFTERNOON_V1_DENSE_TIME_RE = re.compile(
    r"^(?:Afternoon_)?aft_(?P<start>\d+)_(?P<end>\d+)_(?P<camera>\d+)_dense_(?P<dense>[\d.]+)s$",
    re.IGNORECASE,
)
AFTERNOON_V1_DENSE_INDEX_RE = re.compile(
    r"^(?:Afternoon_)?aft_(?P<start>\d+)_(?P<end>\d+)_(?P<camera>\d+)_dense_(?P<dense>\d+)$",
    re.IGNORECASE,
)
AFTERNOON_V1_LEGACY_DENSE_RE = re.compile(
    r"^(?:Afternoon_)?dense_aft_(?P<start>\d+)_(?P<end>\d+)_(?P<camera>\d+)_(?P<dense>\d+)s$",
    re.IGNORECASE,
)
AFTERNOON_V2_DENSE_PREFIX_RE = re.compile(
    r"^(?:AftV2|afternoon_v2)_dense_(?P<ip>\d+\.\d+\.\d+\.\d+)_(?P<camera>\d+)_(?P<clip>\d+)_(?P<dense>[\d.]+)s$",
    re.IGNORECASE,
)
AFTERNOON_V2_DENSE_SUFFIX_RE = re.compile(
    r"^(?:AftV2|afternoon_v2)_(?P<ip>\d+\.\d+\.\d+\.\d+)_(?P<camera>\d+)_(?P<clip>\d+)_dense_(?P<dense>[\d.]+)s$",
    re.IGNORECASE,
)
AFTERNOON_V2_SEGMENT_RE = re.compile(
    r"^(?:AftV2|afternoon_v2)(?:_Dense)?_(?P<ip>\d+\.\d+\.\d+\.\d+)_(?P<camera>\d+)_(?P<clip>\d+)_(?P<segment>\d+)_(?P<frame>\d+)$",
    re.IGNORECASE,
)
AFTERNOON_V2_FRAME_RE = re.compile(
    r"^(?:AftV2|afternoon_v2)_(?P<ip>\d+\.\d+\.\d+\.\d+)_(?P<camera>\d+)_(?P<clip>\d+)_(?P<frame>\d+)$",
    re.IGNORECASE,
)
BATCH_DIR_RE = re.compile(r"^(?P<start>\d+)-(?P<end>\d+)$")


def snake_case(value: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    value = value.replace(".", "_")
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_").lower()


def normalize_seconds(value: str) -> str:
    return snake_case(value)


def normalize_morning_stem(stem: str) -> str | None:
    match = MORNING_RE.match(stem)
    if not match:
        return None

    camera = match.group("camera")
    clip = match.group("clip")
    segment = match.group("segment")
    dense = match.group("dense")
    frame = match.group("frame")

    if dense:
        return (
            f"morning_v1_camera_{camera}_clip_{clip}_segment_{segment}_dense_{normalize_seconds(dense)}s"
        )

    return f"morning_v1_camera_{camera}_clip_{clip}_segment_{segment}_frame_{frame}"


def normalize_afternoon_v1_stem(stem: str) -> str | None:
    match = AFTERNOON_V1_FRAME_RE.match(stem)
    if match:
        return (
            f"afternoon_v1_camera_{match.group('camera')}_segment_{match.group('start')}_{match.group('end')}"
            f"_frame_{match.group('frame')}"
        )

    match = AFTERNOON_V1_DENSE_TIME_RE.match(stem)
    if match:
        return (
            f"afternoon_v1_camera_{match.group('camera')}_segment_{match.group('start')}_{match.group('end')}"
            f"_dense_{normalize_seconds(match.group('dense'))}s"
        )

    match = AFTERNOON_V1_DENSE_INDEX_RE.match(stem)
    if match:
        return (
            f"afternoon_v1_camera_{match.group('camera')}_segment_{match.group('start')}_{match.group('end')}"
            f"_dense_frame_{match.group('dense')}"
        )

    match = AFTERNOON_V1_LEGACY_DENSE_RE.match(stem)
    if match:
        return (
            f"afternoon_v1_camera_{match.group('camera')}_segment_{match.group('start')}_{match.group('end')}"
            f"_dense_{normalize_seconds(match.group('dense'))}s"
        )

    return None


def normalize_afternoon_v2_stem(stem: str) -> str | None:
    match = AFTERNOON_V2_DENSE_PREFIX_RE.match(stem)
    if match:
        return (
            f"afternoon_v2_camera_{match.group('camera')}_clip_{match.group('clip')}"
            f"_dense_{normalize_seconds(match.group('dense'))}s"
        )

    match = AFTERNOON_V2_DENSE_SUFFIX_RE.match(stem)
    if match:
        return (
            f"afternoon_v2_camera_{match.group('camera')}_clip_{match.group('clip')}"
            f"_dense_{normalize_seconds(match.group('dense'))}s"
        )

    match = AFTERNOON_V2_SEGMENT_RE.match(stem)
    if match:
        return (
            f"afternoon_v2_camera_{match.group('camera')}_clip_{match.group('clip')}"
            f"_segment_{match.group('segment')}_frame_{match.group('frame')}"
        )

    match = AFTERNOON_V2_FRAME_RE.match(stem)
    if match:
        return (
            f"afternoon_v2_camera_{match.group('camera')}_clip_{match.group('clip')}"
            f"_frame_{match.group('frame')}"
        )

    return None


def normalize_any_stem(stem: str) -> str:
    for normalizer in (
        normalize_morning_stem,
        normalize_afternoon_v1_stem,
        normalize_afternoon_v2_stem,
    ):
        normalized = normalizer(stem)
        if normalized:
            return normalized

    return snake_case(stem)


def rename_path(source: Path, target: Path) -> None:
    if not source.exists():
        return
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.rename(target)
        return
    except PermissionError:
        if not source.is_dir():
            raise

    target.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        shutil.move(str(child), str(target / child.name))
    source.rmdir()


def rename_with_temporary_names(mapping: dict[Path, Path]) -> int:
    if not mapping:
        return 0

    destination_map: dict[str, Path] = {}
    for source, target in mapping.items():
        key = str(target).lower()
        if key in destination_map and destination_map[key] != source:
            raise RuntimeError(f"Rename collision detected for {target}")
        destination_map[key] = source

    staged: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(mapping.items(), start=1):
        if source == target:
            continue

        temporary = source.with_name(f"__renaming__{index}{source.suffix.lower()}")
        while temporary.exists():
            temporary = temporary.with_name(f"__renaming__{index}_{len(staged)}{source.suffix.lower()}")
        source.rename(temporary)
        staged.append((temporary, target))

    for temporary, target in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(target)

    return len(staged)


def rename_batch_directories(parent: Path) -> int:
    if not parent.exists():
        return 0

    mapping: dict[Path, Path] = {}
    for directory in sorted((p for p in parent.iterdir() if p.is_dir()), key=lambda p: p.name):
        match = BATCH_DIR_RE.match(directory.name)
        if not match:
            continue

        start = int(match.group("start"))
        end = int(match.group("end"))
        target = directory.with_name(f"batch_{start:03d}_{end:03d}")
        if directory != target:
            mapping[directory] = target

    return rename_with_temporary_names(mapping)


def rename_images_in_tree(root: Path) -> int:
    if not root.exists():
        return 0

    mapping: dict[Path, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".png"}:
            continue

        new_stem = normalize_any_stem(path.stem)
        target = path.with_name(f"{new_stem}{path.suffix.lower()}")
        if path != target:
            mapping[path] = target

    return rename_with_temporary_names(mapping)


def rename_yolo_dataset(dataset_dir: Path) -> int:
    if not dataset_dir.exists():
        return 0

    renamed = 0
    for split in ("train", "val", "test"):
        images_dir = dataset_dir / split / "images"
        labels_dir = dataset_dir / split / "labels"
        if not images_dir.exists() or not labels_dir.exists():
            continue

        mapping: dict[Path, Path] = {}
        for image_path in sorted(images_dir.glob("*")):
            if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".png"}:
                continue

            new_stem = normalize_any_stem(image_path.stem)
            target_image = image_path.with_name(f"{new_stem}{image_path.suffix.lower()}")
            if image_path != target_image:
                mapping[image_path] = target_image

            label_path = labels_dir / f"{image_path.stem}.txt"
            if label_path.exists():
                target_label = label_path.with_name(f"{new_stem}.txt")
                if label_path != target_label:
                    mapping[label_path] = target_label

        renamed += rename_with_temporary_names(mapping)

    return renamed


def rewrite_dataset_yaml(dataset_dir: Path) -> None:
    yaml_path = dataset_dir / "dataset.yaml"
    if not yaml_path.exists():
        return

    yaml_path.write_text(
        "\n".join(
            [
                f"path: {dataset_dir.resolve()}",
                "train: train/images",
                "val: val/images",
                "",
                "names:",
                *(f"  {index}: {name}" for index, name in enumerate(YAML_NAMES)),
                "",
            ]
        ),
        encoding="utf-8",
    )


def rewrite_label_export(zip_path: Path, target_name: str) -> None:
    if not zip_path.exists():
        return

    target_path = zip_path.with_name(target_name)
    temporary_path = target_path.with_suffix(".tmp.zip")

    with zipfile.ZipFile(zip_path, "r") as source_zip, zipfile.ZipFile(
        temporary_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as target_zip:
        for info in source_zip.infolist():
            if info.is_dir():
                target_zip.writestr(f"{info.filename.rstrip('/')}/", b"")
                continue

            content = source_zip.read(info.filename)
            new_name = info.filename

            if info.filename.startswith("labels/"):
                label_name = Path(info.filename).name
                if "__" in label_name:
                    hash_prefix, raw_name = label_name.split("__", 1)
                else:
                    hash_prefix, raw_name = "", label_name

                new_stem = normalize_any_stem(Path(raw_name).stem)
                if hash_prefix:
                    new_name = f"labels/{hash_prefix}__{new_stem}.txt"
                else:
                    new_name = f"labels/{new_stem}.txt"

            target_zip.writestr(new_name, content)

    if zip_path != target_path and target_path.exists():
        target_path.unlink()
    zip_path.unlink()
    temporary_path.rename(target_path)


def extract_labels_from_export(zip_path: Path, output_dir: Path) -> None:
    if not zip_path.exists():
        return

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as source_zip:
        for name in source_zip.namelist():
            if not name.startswith("labels/") or name.endswith("/"):
                continue
            output_path = output_dir / Path(name).name
            output_path.write_bytes(source_zip.read(name))


def organize_existing_trained_model(model_dir: Path) -> None:
    if not model_dir.exists():
        return

    metrics_dir = model_dir / "metrics"
    weights_dir = model_dir / "weights"
    validation_dir = model_dir / "validation_previews"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    weights_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    moves = {
        model_dir / "weights" / "best.pt": weights_dir / "best.pt",
        model_dir / "weights" / "last.pt": weights_dir / "last.pt",
        model_dir / "training_args.yaml": model_dir / "training_args.yaml",
        model_dir / "metrics" / "confusion_matrix.png": metrics_dir / "confusion_matrix.png",
        model_dir / "metrics" / "confusion_matrix_normalized.png": metrics_dir / "confusion_matrix_normalized.png",
        model_dir / "metrics" / "results.csv": metrics_dir / "training_metrics.csv",
        model_dir / "metrics" / "results.png": metrics_dir / "training_metrics_overview.png",
        model_dir / "metrics" / "val_batch0_pred.jpg": validation_dir / "validation_batch_0_prediction.jpg",
        model_dir / "metrics" / "val_batch1_pred.jpg": validation_dir / "validation_batch_1_prediction.jpg",
        model_dir / "metrics" / "val_batch2_pred.jpg": validation_dir / "validation_batch_2_prediction.jpg",
        model_dir / "args.yaml": model_dir / "training_args.yaml",
        model_dir / "performance_graphs" / "confusion_matrix.png": metrics_dir / "confusion_matrix.png",
        model_dir / "performance_graphs" / "confusion_matrix_normalized.png": metrics_dir / "confusion_matrix_normalized.png",
        model_dir / "performance_graphs" / "results.csv": metrics_dir / "training_metrics.csv",
        model_dir / "performance_graphs" / "results.png": metrics_dir / "training_metrics_overview.png",
        model_dir / "performance_graphs" / "val_batch0_pred.jpg": validation_dir / "validation_batch_0_prediction.jpg",
        model_dir / "performance_graphs" / "val_batch1_pred.jpg": validation_dir / "validation_batch_1_prediction.jpg",
        model_dir / "performance_graphs" / "val_batch2_pred.jpg": validation_dir / "validation_batch_2_prediction.jpg",
        model_dir / "model_weights" / "best.pt": weights_dir / "best.pt",
        model_dir / "model_weights" / "last.pt": weights_dir / "last.pt",
    }

    for source, target in moves.items():
        if not source.exists() or source == target:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        shutil.move(str(source), str(target))

    for leftover in (
        model_dir / "model_weights",
        model_dir / "performance_graphs",
    ):
        if leftover.exists() and not any(leftover.iterdir()):
            leftover.rmdir()


def organize_colab_run(run_dir: Path, target_model_dir: Path) -> None:
    if not run_dir.exists():
        return

    weights_dir = target_model_dir / "weights"
    metrics_dir = target_model_dir / "metrics"
    training_dir = target_model_dir / "training_previews"
    validation_dir = target_model_dir / "validation_previews"

    for directory in (weights_dir, metrics_dir, training_dir, validation_dir):
        directory.mkdir(parents=True, exist_ok=True)

    moves = {
        run_dir / "weights" / "best.pt": weights_dir / "best.pt",
        run_dir / "weights" / "last.pt": weights_dir / "last.pt",
        run_dir / "args.yaml": target_model_dir / "training_args.yaml",
        run_dir / "BoxF1_curve.png": metrics_dir / "box_f1_curve.png",
        run_dir / "BoxPR_curve.png": metrics_dir / "box_pr_curve.png",
        run_dir / "BoxP_curve.png": metrics_dir / "box_precision_curve.png",
        run_dir / "BoxR_curve.png": metrics_dir / "box_recall_curve.png",
        run_dir / "confusion_matrix.png": metrics_dir / "confusion_matrix.png",
        run_dir / "confusion_matrix_normalized.png": metrics_dir / "confusion_matrix_normalized.png",
        run_dir / "labels.jpg": metrics_dir / "label_distribution.png",
        run_dir / "results.csv": metrics_dir / "training_metrics.csv",
        run_dir / "results.png": metrics_dir / "training_metrics_overview.png",
        run_dir / "train_batch0.jpg": training_dir / "train_batch_0.jpg",
        run_dir / "train_batch1.jpg": training_dir / "train_batch_1.jpg",
        run_dir / "train_batch2.jpg": training_dir / "train_batch_2.jpg",
        run_dir / "train_batch9360.jpg": training_dir / "train_batch_9360.jpg",
        run_dir / "train_batch9361.jpg": training_dir / "train_batch_9361.jpg",
        run_dir / "train_batch9362.jpg": training_dir / "train_batch_9362.jpg",
        run_dir / "train_batch37200.jpg": training_dir / "train_batch_37200.jpg",
        run_dir / "train_batch37201.jpg": training_dir / "train_batch_37201.jpg",
        run_dir / "train_batch37202.jpg": training_dir / "train_batch_37202.jpg",
        run_dir / "val_batch0_labels.jpg": validation_dir / "validation_batch_0_ground_truth.jpg",
        run_dir / "val_batch0_pred.jpg": validation_dir / "validation_batch_0_prediction.jpg",
        run_dir / "val_batch1_labels.jpg": validation_dir / "validation_batch_1_ground_truth.jpg",
        run_dir / "val_batch1_pred.jpg": validation_dir / "validation_batch_1_prediction.jpg",
        run_dir / "val_batch2_labels.jpg": validation_dir / "validation_batch_2_ground_truth.jpg",
        run_dir / "val_batch2_pred.jpg": validation_dir / "validation_batch_2_prediction.jpg",
    }

    for source, target in moves.items():
        if not source.exists():
            continue
        if target.exists():
            target.unlink()
        shutil.move(str(source), str(target))


def remove_label_caches() -> int:
    removed = 0
    for cache_file in DATASETS_DIR.rglob("*.cache"):
        cache_file.unlink()
        removed += 1
    return removed


def remove_empty_directories(root: Path) -> int:
    removed = 0
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        if any(directory.iterdir()):
            continue
        directory.rmdir()
        removed += 1
    return removed


def main() -> None:
    print("Normalizing dataset layout...")

    for old_name, new_name in ROOT_RENAMES.items():
        rename_path(DATASETS_DIR / old_name, DATASETS_DIR / new_name)

    for root_name in ROOT_RENAMES.values():
        root_dir = DATASETS_DIR / root_name
        for old_name, new_name in SUBDIR_RENAMES.items():
            rename_path(root_dir / old_name, root_dir / new_name)

    renamed_batches = 0
    for batch_parent in (
        DATASETS_DIR / "source_afternoon_v1" / "selected_frames",
        DATASETS_DIR / "source_afternoon_v2" / "raw_frames",
        DATASETS_DIR / "source_morning_v1" / "selected_frames",
    ):
        renamed_batches += rename_batch_directories(batch_parent)

    renamed_source_images = 0
    for source_dir in (
        DATASETS_DIR / "source_afternoon_v1" / "selected_frames",
        DATASETS_DIR / "source_afternoon_v2" / "raw_frames",
        DATASETS_DIR / "source_morning_v1" / "selected_frames",
    ):
        renamed_source_images += rename_images_in_tree(source_dir)

    rewrite_label_export(
        DATASETS_DIR / "source_afternoon_v1" / "annotation_exports" / "Afternoon_V1.zip",
        "afternoon_v1_label_studio_yolo_export.zip",
    )
    rewrite_label_export(
        DATASETS_DIR / "source_morning_v1" / "annotation_exports" / "Morning_V1.zip",
        "morning_v1_label_studio_yolo_export.zip",
    )
    rewrite_label_export(
        DATASETS_DIR / "source_afternoon_v2" / "annotation_exports" / "Afternoon_V2.zip",
        "afternoon_v2_label_studio_yolo_export.zip",
    )

    extracted_labels_dir = (
        DATASETS_DIR / "source_afternoon_v2" / "annotation_exports" / "extracted_labels"
    )
    extract_labels_from_export(
        DATASETS_DIR
        / "source_afternoon_v2"
        / "annotation_exports"
        / "afternoon_v2_label_studio_yolo_export.zip",
        extracted_labels_dir,
    )

    renamed_yolo_files = 0
    for dataset_dir in (
        DATASETS_DIR / "source_afternoon_v2" / "yolo_dataset",
        DATASETS_DIR / "merged_dataset_v1" / "yolo_dataset",
        DATASETS_DIR / "merged_dataset_v2" / "yolo_dataset",
    ):
        renamed_yolo_files += rename_yolo_dataset(dataset_dir)
        rewrite_dataset_yaml(dataset_dir)

    organize_existing_trained_model(DATASETS_DIR / "merged_dataset_v1" / "trained_model")

    run_dir = (
        DATASETS_DIR
        / "runs"
        / "detect"
        / "datasets"
        / "merged_v2"
        / "runs"
        / "train_merged"
    )
    organize_colab_run(run_dir, DATASETS_DIR / "merged_dataset_v2" / "trained_model")

    runs_root = DATASETS_DIR / "runs"
    if runs_root.exists():
        shutil.rmtree(runs_root)

    removed_caches = remove_label_caches()
    removed_empty_dirs = remove_empty_directories(DATASETS_DIR)

    print(f"Renamed batch folders: {renamed_batches}")
    print(f"Renamed source images: {renamed_source_images}")
    print(f"Renamed YOLO images and labels: {renamed_yolo_files}")
    print(f"Removed cache files: {removed_caches}")
    print(f"Removed empty directories: {removed_empty_dirs}")
    print("Dataset normalization complete.")


if __name__ == "__main__":
    main()
