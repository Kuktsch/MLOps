"""Загрузка модели, chat template и генерация.

Этот модуль — единая реализация инференса для ``src.generate`` и
``src.bench``. Имя модели всегда приходит из ``params.yaml``.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def set_seed(seed: int) -> None:
    """Зафиксировать основные источники случайности."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _torch_dtype(dtype_name: str) -> torch.dtype:
    """Преобразовать строковое имя dtype из конфига в ``torch.dtype``."""
    dtype = getattr(torch, dtype_name, None)
    if not isinstance(dtype, torch.dtype):
        raise ValueError(f"Неизвестный torch dtype: {dtype_name!r}")
    return dtype


def load_model(params: dict[str, Any]):
    """Загрузить токенизатор и модель согласно ``params.yaml``."""
    model_cfg = params["model"]
    name = model_cfg["name"]
    device = model_cfg.get("device", "auto")

    tokenizer = AutoTokenizer.from_pretrained(name)

    # ``device_map`` принимает "auto" либо конкретное устройство, на которое
    # нужно поместить всю модель. Это сохраняет единый конфиг для CPU/CUDA/MPS.
    model = AutoModelForCausalLM.from_pretrained(
        name,
        dtype=_torch_dtype(model_cfg["dtype"]),
        device_map=device,
    )
    model.eval()
    return tokenizer, model


def build_prompt(tokenizer, params: dict[str, Any], text: str) -> str:
    """Собрать пользовательский промпт штатным chat template модели."""
    messages = [{"role": "user", "content": text}]
    template_kwargs: dict[str, Any] = {}

    # Дополнительные kwargs доступны Jinja-шаблону. У моделей без thinking-
    # режима неиспользуемый параметр не влияет на сформированный промпт.
    if "enable_thinking" in params["generate"]:
        template_kwargs["enable_thinking"] = params["generate"]["enable_thinking"]

    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        **template_kwargs,
    )


def generate(tokenizer, model, params: dict[str, Any], text: str) -> tuple[str, int]:
    """Сгенерировать ответ и вернуть текст вместе с числом новых токенов."""
    prompt = build_prompt(tokenizer, params, text)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    generation_cfg = params["generate"]
    temperature = float(generation_cfg["temperature"])

    generation_kwargs: dict[str, Any] = {
        "max_new_tokens": int(generation_cfg["max_new_tokens"]),
        "do_sample": temperature > 0,
    }
    # Не передаём temperature при greedy decoding: transformers предупреждает,
    # что параметр не используется при do_sample=False.
    if temperature > 0:
        generation_kwargs["temperature"] = temperature

    with torch.inference_mode():
        output = model.generate(**inputs, **generation_kwargs)

    input_len = inputs["input_ids"].shape[1]
    new_tokens = output[0][input_len:]
    text_out = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return text_out, int(new_tokens.numel())
