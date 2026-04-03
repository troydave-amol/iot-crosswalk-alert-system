import json
import io

with open('train_yolov8.ipynb', 'r', encoding='utf-8') as f:
    d = json.load(f)

d['cells'][3]['source'][2] = "project_dir = (Path.cwd() / 'datasets' / 'merged_v2' / 'training_runs').resolve()\n"
d['cells'][3]['source'][3] = "dataset_yaml = (Path.cwd() / 'datasets' / 'merged_v2' / 'data.yaml').resolve()\n"
d['cells'][5]['source'][3] = "best_model = (Path.cwd() / 'datasets' / 'merged_v2' / 'training_runs' / 'colab_train_merged_v2' / 'weights' / 'best.pt').resolve()\n"
d['cells'][3]['source'][0] = "from pathlib import Path\n"
d['cells'][3]['source'][1] = "\n"

# Only train on the newest weights as transfer learning to speed it up!
# d['cells'][3]['source'].insert(0, "model = YOLO(str(best_model_old))\n") - Wait, the cell 3 re-imported from yolov8n.pt

with open('train_yolov8.ipynb', 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=1)
