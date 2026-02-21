"""
Setup script for Smart Crosswalk Alert System datasets.
Phase A: CityPersons extraction + YAML setup
Phase B: JAAD YOLO format YAML setup (already extracted)
"""

import zipfile
import os
import shutil
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
DATASETS_DIR   = PROJECT_ROOT / "datasets"

CITYPERSONS_ZIP = Path(r"C:\Users\Acer\.cache\kagglehub\datasets\hakurei\citypersons\versions\1\CityPersons")
JAAD_SRC        = Path(r"C:\Users\Acer\.cache\kagglehub\datasets\charvik\jaad-frames-dataset-10-v1-yolo-format\versions\1")

CITYPERSONS_DEST = DATASETS_DIR / "citypersons"
JAAD_DEST        = DATASETS_DIR / "jaad"


# ── Helpers ────────────────────────────────────────────────────────────────────
def bar(done, total, width=40):
    pct = done / total
    filled = int(width * pct)
    b = "#" * filled + "-" * (width - filled)
    print(f"\r  [{b}] {done}/{total} ({pct*100:.1f}%)", end="", flush=True)


# ── Phase A: Extract CityPersons ───────────────────────────────────────────────
def extract_citypersons():
    print("=" * 60)
    print("PHASE A — Extracting CityPersons")
    print("=" * 60)

    if CITYPERSONS_DEST.exists():
        print(f"  ✔ Already exists: {CITYPERSONS_DEST}")
        print("  Skipping extraction.")
        return

    CITYPERSONS_DEST.mkdir(parents=True, exist_ok=True)

    z = zipfile.ZipFile(CITYPERSONS_ZIP)
    members = [n for n in z.namelist() if n.startswith("Citypersons/") and not n.endswith("/")]
    total = len(members)
    print(f"  Extracting {total} files…")

    for i, member in enumerate(members, 1):
        # Strip leading "Citypersons/" so we get images/train/... directly
        rel = Path(member).relative_to("Citypersons")
        dest_file = CITYPERSONS_DEST / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        with z.open(member) as src, open(dest_file, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if i % 100 == 0 or i == total:
            bar(i, total)

    z.close()
    print(f"\n  ✔ CityPersons extracted to: {CITYPERSONS_DEST}")


# ── Phase B: Set up JAAD ───────────────────────────────────────────────────────
def setup_jaad():
    print()
    print("=" * 60)
    print("PHASE B — Setting up JAAD")
    print("=" * 60)

    if JAAD_DEST.exists():
        print(f"  ✔ Already exists: {JAAD_DEST}")
    else:
        print(f"  Copying JAAD from cache…")
        shutil.copytree(JAAD_SRC, JAAD_DEST)
        print(f"  ✔ JAAD copied to: {JAAD_DEST}")


# ── Write data YAML files ──────────────────────────────────────────────────────
def write_yamls():
    print()
    print("=" * 60)
    print("Writing data.yaml files")
    print("=" * 60)

    # CityPersons YAML — single class: person (Phase A)
    cp_yaml = DATASETS_DIR / "citypersons.yaml"
    cp_yaml.write_text(f"""\

# CityPersons — Phase A base pedestrian detector
# Classes: person only (will become child_pedestrian / adult_pedestrian in Phase D)

path: {CITYPERSONS_DEST.as_posix()}
train: images/train
val:   images/val
test:  images/test

nc: 1
names:
  0: person
""", encoding='utf-8')
    print(f"  OK: {cp_yaml}")

    # JAAD YAML — merge 3 redundant classes → person (Phase B)
    jaad_yaml = DATASETS_DIR / "jaad.yaml"
    jaad_yaml.write_text(f"""\

# JAAD Frames — Phase B domain fine-tuning
# Original classes: pedestrian(0), ped(1), people(2) → all mapped to person
# NOTE: labels remain 0/1/2 but all represent "person" — treat as single class

path: {JAAD_DEST.as_posix()}
train: images/train
val:   images/val
test:  images/test

nc: 3
names:
  0: pedestrian
  1: ped
  2: people

# For single-class training, use the remap script below to merge to class 0
""", encoding='utf-8')
    print(f"  OK: {jaad_yaml}")

    # Final merged schema placeholder (Phase D)
    schema_yaml = DATASETS_DIR / "crosswalk_child.yaml"
    schema_yaml.write_text(f"""\

# Smart Crosswalk — Phase D final schema (child-classified pedestrians)
# Populate images/ and labels/ after manual annotation (2,000 child instances)

path: {(DATASETS_DIR / 'crosswalk_child').as_posix()}
train: images/train
val:   images/val
test:  images/test

nc: 2
names:
  0: child_pedestrian
  1: adult_pedestrian
""", encoding='utf-8')
    print(f"  OK: {schema_yaml} (Phase D placeholder)")


# ── Print summary ──────────────────────────────────────────────────────────────
def print_summary():
    print()
    print("=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)

    for split in ["train", "val", "test"]:
        imgs = list((CITYPERSONS_DEST / "images" / split).glob("*")) if (CITYPERSONS_DEST / "images" / split).exists() else []
        lbls = list((CITYPERSONS_DEST / "labels" / split).glob("*.txt")) if (CITYPERSONS_DEST / "labels" / split).exists() else []
        print(f"  CityPersons [{split:5s}]: {len(imgs):4d} images, {len(lbls):4d} labels")

    print()
    for split in ["train", "val", "test"]:
        imgs = list((JAAD_DEST / "images" / split).glob("*")) if (JAAD_DEST / "images" / split).exists() else []
        lbls = list((JAAD_DEST / "labels" / split).glob("*.txt")) if (JAAD_DEST / "labels" / split).exists() else []
        print(f"  JAAD        [{split:5s}]: {len(imgs):4d} images, {len(lbls):4d} labels")

    print()
    print("Next steps:")
    print("  Phase A → python train_phase_a.py")
    print("  Phase B → python train_phase_b.py  (after Phase A completes)")
    print("  Phase D → annotate 2,000 child instances, then train")


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    extract_citypersons()
    setup_jaad()
    write_yamls()
    print_summary()
    print()
    print("✔ Setup complete!")
