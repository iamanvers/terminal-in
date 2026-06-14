"""Build the SFT dataset locally and write a single self-contained
`dataset.jsonl` to upload to Colab for 3B GPU training.

Why this exists: the dataset blends public corpora (downloadable anywhere) with
the system's OWN data — closed trades + hindsight-judged planner decisions from
the local SQLite DB. Colab can't see that DB, so we export the fully-formatted
jsonl here and carry it up. Each row already has a `text` field (the formatted
training example), so the Colab side needs nothing but this file.

Run:  .venv/Scripts/python.exe scripts/export_dataset.py
Out:  data/training/colab/dataset.jsonl   (upload this to the Colab notebook)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from terminal_in.agents.training.prepare_dataset import prepare

OUT = Path('data/training/colab')


def main() -> None:
    counts = prepare(output_dir=OUT)
    jsonl = (OUT / 'dataset.jsonl').resolve()
    size_mb = jsonl.stat().st_size / 1e6 if jsonl.exists() else 0
    print('\n' + '=' * 60)
    print(f'  dataset.jsonl  →  {jsonl}')
    print(f'  {counts.get("total", "?")} samples · {size_mb:.1f} MB')
    print(f'  composition: {counts}')
    print('  Upload this file to colab/train_3b_colab.ipynb (the UPLOAD cell).')
    print('=' * 60)


if __name__ == '__main__':
    main()
