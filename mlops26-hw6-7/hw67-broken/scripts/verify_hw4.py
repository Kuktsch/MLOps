"""Проверить все тензоры повторной токенизацией исходной функцией HW4."""
import json
import sys
from pathlib import Path

import torch
import yaml
from transformers import AutoTokenizer

root = Path(__file__).resolve().parents[1]
hw4 = root.parents[1] / 'hw4-broken'
sys.path.insert(0, str(hw4))
from src.tokenize_data import encode_example

params = yaml.safe_load((hw4 / 'params.yaml').read_text())
tokenizer = AutoTokenizer.from_pretrained(params['model']['name'], revision='c1899de289a04d12100db370d81485cdf75e47ca', local_files_only=True)
tokenizer.padding_side = params['tokenize']['padding_side']
results = {}
for split in ('train', 'val'):
    records = [json.loads(line) for line in (root / f'data/source/{split}.jsonl').read_text().splitlines()]
    blob = torch.load(root / f'data/tokenized/{split}.pt', weights_only=True)
    expected = []
    for record in records:
        encoded = encode_example(tokenizer, record, params, params['tokenize']['max_seq_len'])
        meta = encoded.pop('_meta')
        if meta['supervised']:
            expected.append(encoded)
    if expected != blob['examples'] or blob['model'] != params['model']['name']:
        raise ValueError(f'{split}: тензоры не совпадают с токенизацией сырого источника HW4')
    results[split] = dict(raw_rows=len(records), tokenized_rows=len(expected), all_examples_equal=True)
path = root / 'metrics/tokenization-proof.json'
path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
print(path.read_text())
