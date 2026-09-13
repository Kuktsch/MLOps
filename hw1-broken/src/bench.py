"""Замер производительности машины на выбранной модели.

Три метрики измеряются раздельно:
  * время загрузки модели — разовая стоимость старта;
  * tokens/sec — только генерация после прогрева;
  * peak RSS — пиковая резидентная память процесса.
"""

from __future__ import annotations

import json
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

import psutil
import torch

from src.config import load_params
from src.model import generate, load_model, set_seed



def hardware_info() -> dict[str, object]:
    """Собрать базовую информацию о машине для отчёта."""
    cpu_name = platform.processor().strip()
    if not cpu_name and sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("model name"):
                    cpu_name = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass

    info: dict[str, object] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": cpu_name or "unknown",
        "ram_gib": round(psutil.virtual_memory().total / (1024**3), 2),
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        index = torch.cuda.current_device()
        props = torch.cuda.get_device_properties(index)
        info["gpu"] = props.name
        info["gpu_vram_gib"] = round(props.total_memory / (1024**3), 2)
    return info


def peak_rss_mb() -> float:
    """Вернуть пиковую RSS текущего процесса в MiB.

    ``ru_maxrss`` измеряется в байтах на macOS и в KiB на Linux/WSL.
    """
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024**2) if sys.platform == "darwin" else peak / 1024


def _sync_device(model) -> None:
    """Дождаться завершения асинхронных GPU/MPS операций перед таймингом."""
    device = model.device
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps" and hasattr(torch, "mps"):
        torch.mps.synchronize()


def main() -> None:
    params = load_params()
    prompt = params["bench"]["prompt"]
    seed = int(params["generate"]["seed"])
    set_seed(seed)

    # 1) Отдельно измеряем только загрузку токенизатора и модели.
    load_started = time.perf_counter()
    tokenizer, model = load_model(params)
    load_time = time.perf_counter() - load_started

    # 2) Прогрев не входит в итоговую скорость.
    for _ in range(int(params["bench"]["warmup_runs"])):
        generate(tokenizer, model, params, prompt)
    _sync_device(model)

    # 3) Каждый измерительный прогон имеет собственный таймер.
    speeds: list[float] = []
    runs: list[dict[str, float | int]] = []
    for _ in range(int(params["bench"]["measure_runs"])):
        _sync_device(model)
        started = time.perf_counter()
        _, n_tokens = generate(tokenizer, model, params, prompt)
        _sync_device(model)
        elapsed = time.perf_counter() - started

        speed = n_tokens / elapsed if elapsed > 0 else 0.0
        speeds.append(speed)
        runs.append(
            {
                "elapsed_sec": round(elapsed, 4),
                "tokens": n_tokens,
                "tokens_per_sec": round(speed, 2),
            }
        )

    report = {
        "hardware": hardware_info(),
        "model": params["model"]["name"],
        "device": str(model.device),
        "dtype": params["model"]["dtype"],
        "load_time_sec": round(load_time, 2),
        "tokens_per_sec": round(statistics.median(speeds), 2),
        "tokens_per_sec_all": [round(s, 2) for s in speeds],
        "runs": runs,
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "warmup_runs": int(params["bench"]["warmup_runs"]),
        "measure_runs": int(params["bench"]["measure_runs"]),
    }

    Path("docs").mkdir(exist_ok=True)
    Path("docs/bench.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
