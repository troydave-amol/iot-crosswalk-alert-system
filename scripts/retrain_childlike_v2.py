"""
retrain_childlike_v2.py — End-to-end retraining automation

Steps:
  1. Clear old JAAD export output
  2. Re-export JAAD with fixed mapping (young → child_like)
  3. Clear old FT split output
  4. Resplit for fine-tuning
  5. Fine-tune 30 epochs from current best weights
  6. Copy new best.pt to models/

Usage:
  python scripts/retrain_childlike_v2.py
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
DATASETS     = PROJECT_ROOT / "datasets"

JAAD_EXPORT_SCRIPT = DATASETS / "jaad_source" / "JAAD" / "export_jaad_childlike_yolo.py"
JAAD_EXPORT_OUT    = DATASETS / "jaad_childlike_yolo"

RESPLIT_SCRIPT     = PROJECT_ROOT / "scripts" / "resplit_jaad_childlike_ft.py"
FT_DATASET         = DATASETS / "jaad_childlike_ft"
FT_DATA_YAML       = FT_DATASET / "data.yaml"

CURRENT_BEST       = PROJECT_ROOT / "models" / "yolov8_childlike_best.pt"

# ── Training Config ────────────────────────────────────────────────────────────
EPOCHS   = 30
BATCH    = 8
IMGSZ    = 640
WORKERS  = 2      # keep low to avoid Windows pagefile OOM
FREEZE   = 10     # freeze early backbone layers
PATIENCE = 15


def run_script(script_path: Path, label: str, extra_env: dict | None = None):
    """Run a Python script as a subprocess and stream output."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Script: {script_path}")
    print(f"{'='*60}\n")

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(script_path.parent),
        env=env,
    )

    if result.returncode != 0:
        print(f"\n!! {label} FAILED (exit code {result.returncode})")
        sys.exit(1)

    print(f"\n✔ {label} completed successfully.")


def clear_dir(path: Path, label: str):
    """Remove a directory if it exists."""
    if path.exists():
        print(f"  Clearing {label}: {path}")
        shutil.rmtree(path)
        print(f"  ✔ Removed.")
    else:
        print(f"  {label} does not exist, skipping clear.")


def main():
    print("=" * 60)
    print("  RETRAIN CHILDLIKE v2")
    print("  young → child_like mapping fix + 30-epoch fine-tune")
    print("=" * 60)

    # Verify prerequisites
    if not JAAD_EXPORT_SCRIPT.exists():
        print(f"!! Export script not found: {JAAD_EXPORT_SCRIPT}")
        sys.exit(1)

    if not RESPLIT_SCRIPT.exists():
        print(f"!! Resplit script not found: {RESPLIT_SCRIPT}")
        sys.exit(1)

    if not CURRENT_BEST.exists():
        print(f"!! Current best model not found: {CURRENT_BEST}")
        print("   Cannot fine-tune without a base model.")
        sys.exit(1)

    # ── Step 1: Clear old export ───────────────────────────────────────────────
    print("\n--- Step 1/5: Clear old JAAD export ---")
    clear_dir(JAAD_EXPORT_OUT, "JAAD export output")

    # ── Step 2: Re-export with fixed mapping ───────────────────────────────────
    print("\n--- Step 2/5: Re-export JAAD (young → child_like) ---")
    run_script(JAAD_EXPORT_SCRIPT, "JAAD Export")

    # ── Step 3: Clear old FT split ─────────────────────────────────────────────
    print("\n--- Step 3/5: Clear old FT split ---")
    clear_dir(FT_DATASET, "FT dataset")

    # ── Step 4: Resplit for fine-tuning ────────────────────────────────────────
    print("\n--- Step 4/5: Resplit dataset ---")
    run_script(
        RESPLIT_SCRIPT,
        "Resplit",
        extra_env={
            "JAAD_CHILDLIKE_SRC": str(JAAD_EXPORT_OUT),
            "JAAD_CHILDLIKE_DST": str(FT_DATASET),
        },
    )

    if not FT_DATA_YAML.exists():
        print(f"!! data.yaml not found after resplit: {FT_DATA_YAML}")
        sys.exit(1)

    # ── Step 5: Fine-tune ──────────────────────────────────────────────────────
    print(f"\n--- Step 5/5: Fine-tune for {EPOCHS} epochs ---")
    print(f"  Base model: {CURRENT_BEST}")
    print(f"  Dataset:    {FT_DATA_YAML}")
    print(f"  Epochs:     {EPOCHS}")
    print(f"  Batch:      {BATCH}")
    print(f"  Freeze:     {FREEZE} layers")

    from ultralytics import YOLO

    model = YOLO(str(CURRENT_BEST))
    results = model.train(
        data=str(FT_DATA_YAML),
        epochs=EPOCHS,
        batch=BATCH,
        imgsz=IMGSZ,
        workers=WORKERS,
        freeze=FREEZE,
        patience=PATIENCE,
        name="retrain_v2",
        exist_ok=True,
        verbose=True,
    )

    # ── Copy best.pt to models/ ────────────────────────────────────────────────
    train_dir = Path(results.save_dir) if hasattr(results, 'save_dir') else None

    # Fallback: search for the retrain_v2 run directory
    if train_dir is None or not (train_dir / "weights" / "best.pt").exists():
        for candidate in sorted(PROJECT_ROOT.glob("runs/detect/retrain_v2*"), reverse=True):
            if (candidate / "weights" / "best.pt").exists():
                train_dir = candidate
                break

    if train_dir and (train_dir / "weights" / "best.pt").exists():
        new_best = train_dir / "weights" / "best.pt"
        shutil.copy2(new_best, CURRENT_BEST)
        print(f"\n✔ Copied new best.pt → {CURRENT_BEST}")
        print(f"  Source: {new_best}")
        print(f"  Size:   {CURRENT_BEST.stat().st_size:,} bytes")
    else:
        print("\n!! Could not locate best.pt after training.")
        print("   Check runs/detect/retrain_v2/weights/ manually.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✔ RETRAIN COMPLETE")
    print(f"  Model ready at: {CURRENT_BEST}")
    print("  Restart app.py to use the new model.")
    print("=" * 60)


if __name__ == "__main__":
    main()
