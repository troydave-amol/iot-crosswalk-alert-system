import shutil, re
from pathlib import Path

PROJECT_ROOT = Path(r'C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics')
BASE_DIR     = PROJECT_ROOT / 'datasets' / 'August 11, 2026 Frames'
OUTPUT_DIR   = BASE_DIR / 'batches'
BATCH_SIZE   = 100

SCENARIO_PATHS = [
    BASE_DIR / 'Morning',
    BASE_DIR / 'Afternoon' / '12 pm',
    BASE_DIR / 'Afternoon' / '2 pm',
]

def natural_sort_key(path):
    parts = re.split(r'(\d+)', path.stem)
    return [int(p) if p.isdigit() else p.lower() for p in parts]

all_frames = []
for scenario_path in SCENARIO_PATHS:
    if not scenario_path.exists():
        print(f'  [WARN] Missing: {scenario_path}')
        continue
    video_dirs = sorted([d for d in scenario_path.iterdir() if d.is_dir()], key=natural_sort_key)
    print(f'\nScenario: {scenario_path.relative_to(BASE_DIR)}  ({len(video_dirs)} clips)')
    for vdir in video_dirs:
        frames = sorted(vdir.glob('*.jpg'), key=natural_sort_key)
        print(f'  {vdir.name}/ -> {len(frames)} frames')
        all_frames.extend(frames)

total = len(all_frames)
num_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
print(f'\nTotal: {total} frames  |  Batches: {num_batches}')

if OUTPUT_DIR.exists():
    shutil.rmtree(OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True)

for bi in range(num_batches):
    bn = bi + 1
    folder = OUTPUT_DIR / f'batch_{bn:03d}'
    folder.mkdir()
    start = bi * BATCH_SIZE
    end   = min(start + BATCH_SIZE, total)
    for si, src in enumerate(all_frames[start:end]):
        dest = folder / f'frame_{start+si+1:05d}.jpg'
        shutil.copy2(src, dest)
    print(f'  batch_{bn:03d}/ -> {end-start} frames  (frame_{start+1:05d}-frame_{end:05d})')

print(f'\nDone! Output: {OUTPUT_DIR}')
