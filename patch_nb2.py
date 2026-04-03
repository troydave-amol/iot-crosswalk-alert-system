import json
import io
from pathlib import Path

nb_path = 'train_3_2.0.ipynb'
if not Path(nb_path).exists():
    nb_path = next(Path('.').glob('*.ipynb')).name

with open(nb_path, 'r', encoding='utf-8') as f:
    d = json.load(f)

for cell in d['cells']:
    if cell['cell_type'] == 'code':
        for i in range(len(cell['source'])):
            cell['source'][i] = cell['source'][i].replace('merged_dataset_v2', 'merged_v2').replace('yolo_dataset/dataset.yaml', 'data.yaml')
            
with open(nb_path, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=1)
