import os, random, shutil
from pathlib import Path

# ===== EDIT THESE PATHS IF NEEDED =====
SRC = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\_archive\jaad_childlike_yolo")
DST = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\jaad_childlike_ft")

SEED = 42

# Split ratios (for CHILD-CONTAINING images)
CHILD_SPLIT = {"train": 0.80, "val": 0.10, "test": 0.10}

# Minimum number of child-containing images per split (prevents "0 child in val")
MIN_CHILD_IMAGES = {"train": 200, "val": 40, "test": 60}  # script auto-adjusts if dataset is smaller

# Sampling strategy
KEEP_ONLY_CHILD_FRAMES = True     # best for imbalance: keep frames that contain >=1 child_like
ADD_ADULT_ONLY_RATIO = 0.25       # add adult-only frames equal to 25% of child frames per split (set 0 to skip)

# ===== DO NOT EDIT BELOW =====

def ensure_dirs(root: Path):
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

def parse_label(label_path: Path):
    child = 0
    adult = 0
    if not label_path.exists():
        return child, adult
    for line in label_path.read_text(encoding="utf-8").strip().splitlines():
        if not line.strip():
            continue
        cls = line.split()[0]
        if cls == "0":
            child += 1
        elif cls == "1":
            adult += 1
    return child, adult

def build_index(src: Path):
    # Collect all image/label pairs across all splits in SRC
    items = []
    for split in ("train", "val", "test"):
        img_dir = src / "images" / split
        lbl_dir = src / "labels" / split
        for img in img_dir.glob("*.png"):
            base = img.stem
            lbl = lbl_dir / f"{base}.txt"
            c, a = parse_label(lbl)
            items.append({
                "img": img,
                "lbl": lbl,
                "base": base,
                "child": c,
                "adult": a,
                "has_child": c > 0
            })
    return items

def pick_child_splits(child_items):
    random.shuffle(child_items)

    n = len(child_items)
    if n == 0:
        raise SystemExit("No child-containing images found. Cannot build child_like dataset.")

    # Compute split sizes
    n_train = int(n * CHILD_SPLIT["train"])
    n_val   = int(n * CHILD_SPLIT["val"])
    n_test  = n - n_train - n_val

    # Apply minimums safely
    mins = {k: min(MIN_CHILD_IMAGES[k], n) for k in MIN_CHILD_IMAGES}
    # If dataset is small, scale minimums down proportionally
    total_min = mins["train"] + mins["val"] + mins["test"]
    if total_min > n:
        # scale down
        scale = n / total_min
        mins = {k: max(1, int(mins[k] * scale)) for k in mins}
        # fix any rounding drift
        drift = n - (mins["train"] + mins["val"] + mins["test"])
        mins["train"] += drift

    n_train = max(n_train, mins["train"])
    n_val   = max(n_val, mins["val"])
    n_test  = max(n_test, mins["test"])

    # Fix if totals exceed n due to mins
    if n_train + n_val + n_test > n:
        overflow = (n_train + n_val + n_test) - n
        # reduce train first
        n_train = max(1, n_train - overflow)

    train = child_items[:n_train]
    val   = child_items[n_train:n_train+n_val]
    test  = child_items[n_train+n_val:n_train+n_val+n_test]
    return {"train": train, "val": val, "test": test}

def sample_adult_only(adult_items, k):
    if k <= 0 or not adult_items:
        return []
    random.shuffle(adult_items)
    return adult_items[:min(k, len(adult_items))]

def copy_items(items, split, dst: Path):
    img_out = dst / "images" / split
    lbl_out = dst / "labels" / split

    imgs = 0
    child_inst = 0
    adult_inst = 0

    for it in items:
        # unique naming to avoid collisions (since we mix old splits)
        new_base = f"{it['img'].parent.name}_{it['base']}"
        dst_img = img_out / f"{new_base}.png"
        dst_lbl = lbl_out / f"{new_base}.txt"

        shutil.copy2(it["img"], dst_img)
        shutil.copy2(it["lbl"], dst_lbl)

        imgs += 1
        child_inst += it["child"]
        adult_inst += it["adult"]

    return imgs, child_inst, adult_inst

def write_yaml(dst: Path):
    yaml = f"""path: {dst.as_posix()}
train: images/train
val: images/val
test: images/test

names:
  0: child_like
  1: adult_like
"""
    (dst / "data.yaml").write_text(yaml, encoding="utf-8")

def main():
    random.seed(SEED)

    if not SRC.exists():
        raise SystemExit(f"SRC not found: {SRC}")

    ensure_dirs(DST)

    items = build_index(SRC)
    child_items = [x for x in items if x["has_child"]]
    adult_only_items = [x for x in items if not x["has_child"]]

    print(f"Found images total={len(items)} | child_frames={len(child_items)} | adult_only_frames={len(adult_only_items)}")

    splits = pick_child_splits(child_items)

    # Build final items per split
    final = {}
    for split in ("train", "val", "test"):
        chosen = list(splits[split])
        if not KEEP_ONLY_CHILD_FRAMES:
            # if we want to keep everything, we'd add all adult-only later; not recommended for deadline.
            pass

        # Add a small amount of adult-only frames as negatives
        add_k = int(len(chosen) * ADD_ADULT_ONLY_RATIO)
        chosen += sample_adult_only(adult_only_items, add_k)

        final[split] = chosen

    # Copy and summarize
    summary = {}
    for split in ("train", "val", "test"):
        imgs, c, a = copy_items(final[split], split, DST)
        summary[split] = {"images": imgs, "child_like": c, "adult_like": a}

    write_yaml(DST)

    print("\n=== FT DATASET SUMMARY ===")
    for split in ("train", "val", "test"):
        s = summary[split]
        print(f"{split}: images={s['images']}, child_like={s['child_like']}, adult_like={s['adult_like']}")
    print(f"data.yaml -> {DST / 'data.yaml'}")

    # Quick validation: ensure val has child_like
    if summary["val"]["child_like"] == 0:
        print("\n!! WARNING: val still has 0 child_like instances. Increase MIN_CHILD_IMAGES['val'] or reduce FRAME_STRIDE in export.")
    else:
        print("\nOK: val contains child_like instances.")

if __name__ == "__main__":
    main()
