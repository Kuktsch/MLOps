"""One generation implementation shared by full evaluation and the HTTP API."""
import importlib.metadata
import time
from pathlib import Path


class StubBackend:
    label = 'STUB ONLY'

    def __init__(self, manifest, root=None):
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = 0
        self.warmup_calls = 0

    def validate_prompt(self, prompt):
        return None

    def warmup(self):
        self.warmup_calls += 1
        time.sleep(.01)

    def generate(self, prompt, limit):
        self.calls += 1
        time.sleep(.01)
        return {'answer': f'STUB ONLY: {self.loaded_id}', 'output_tokens': 1}


class TransformersBackend:
    label = 'Transformers + PEFT (real weights)'

    def __init__(self, manifest, root):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from artifacts import local_path
        self.loaded_id = manifest['model_id']
        self.runtime_sha256 = manifest['runtime_sha256']
        self.calls = self.warmup_calls = 0
        self.runtime = runtime = manifest['runtime']
        for name, expected in runtime['libraries'].items():
            if importlib.metadata.version(name) != expected:
                raise ValueError(f'{name} version changed: reevaluate')
        if runtime['generation']['do_sample'] is not False:
            raise ValueError('Only evaluated deterministic decoding is supported')
        self.device = runtime['device']
        self.tokenizer = AutoTokenizer.from_pretrained(local_path(root, runtime['tokenizer_uri']), local_files_only=True)
        if self.tokenizer.chat_template is None:
            raise ValueError('Missing chat template')
        from release import digest
        if digest(self.tokenizer.chat_template.encode()) != runtime['template_sha256']:
            raise ValueError('Loaded template mismatch')
        torch.manual_seed(runtime['generation']['seed'])
        self.model = AutoModelForCausalLM.from_pretrained(
            local_path(root, runtime['base_uri']), local_files_only=True,
            dtype=getattr(torch, runtime['dtype']))
        if manifest['model_kind'] == 'adapter':
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, local_path(root, manifest['artifact_uri']), local_files_only=True)
        self.model.to(self.device).eval()
        if str(self.model.dtype).removeprefix('torch.') != runtime['dtype']:
            raise ValueError('Actual model dtype differs from evaluated dtype')

    def batch(self, prompt):
        g = self.runtime['generation']
        text = self.tokenizer.apply_chat_template(
            [{'role': 'system', 'content': g['system']}, {'role': 'user', 'content': prompt}],
            tokenize=False, add_generation_prompt=True, enable_thinking=g['enable_thinking'])
        return self.tokenizer(text, return_tensors='pt')

    def validate_prompt(self, prompt):
        if self.batch(prompt)['input_ids'].shape[1] > self.runtime['max_input_tokens']:
            raise ValueError('Input exceeds evaluated service token limit')

    def infer(self, prompt, limit):
        import torch
        batch = self.batch(prompt).to(self.device)
        if batch['input_ids'].shape[1] > self.runtime['max_input_tokens']:
            raise ValueError('Input too long')
        if self.device.startswith('cuda'):
            torch.cuda.synchronize()
        with torch.inference_mode():
            out = self.model.generate(**batch, max_new_tokens=limit, do_sample=False,
                                      pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id)
        if self.device.startswith('cuda'):
            torch.cuda.synchronize()
        tokens = out[0, batch['input_ids'].shape[1]:]
        return {'answer': self.tokenizer.decode(tokens, skip_special_tokens=True), 'output_tokens': len(tokens)}

    def warmup(self):
        self.warmup_calls += 1
        self.infer('Какой химический символ у кислорода? choices: O, H, N.', self.runtime['generation']['max_new_tokens'])

    def generate(self, prompt, limit):
        self.calls += 1
        if limit != self.runtime['generation']['max_new_tokens']:
            raise ValueError('Only the evaluated generation limit is supported')
        return self.infer(prompt, limit)
