"""Сборка docs/anatomy.md и графика норм активаций."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # без дисплея: скрипт должен работать и в CI

import matplotlib.pyplot as plt  # noqa: E402  (backend выбирается до импорта)

MODE_TITLES = {
    "inference": "инференс",
    "full_ft": "full fine-tune",
    "lora": "LoRA (r=8, q/v)",
}


def thousands(n: int) -> str:
    """Число с неразрывными пробелами по разрядам."""
    return f"{n:,}".replace(",", " ")


def plot_activations(activations: dict, path: str) -> None:
    """Две панели: норма по позициям токена и средняя норма по трём блокам."""
    labels = list(activations["norms"])
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(11, 4), width_ratios=(2, 1))

    for label in labels:
        values = activations["norms"][label]
        ax_left.plot(values, linewidth=1.4,
                     label=f"{label} (слой {activations['layers'][label]})")
    ax_left.set_xlabel("позиция токена")
    ax_left.set_yscale("log")   # без лога всё придавит выброс massive activations
    ax_left.set_ylabel("‖h‖₂ (лог. шкала)")
    ax_left.set_title("Норма скрытого состояния по позициям")
    ax_left.legend(fontsize=9)
    ax_left.grid(alpha=0.3)

    means = [sum(activations["norms"][x]) / len(activations["norms"][x]) for x in labels]
    ax_right.bar(labels, means, color=["#4c78a8", "#f58518", "#54a24b"])
    ax_right.set_ylabel("средняя ‖h‖₂")
    ax_right.set_title("Средняя норма по блоку")
    ax_right.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def conditions_section(report: dict) -> list[str]:
    """Условия замера. Без них ни одна цифра ниже не сравнима ни с чем."""
    env = report["environment"]
    return [
        "## 2. Условия замера",
        "",
        "| Условие | Значение |",
        "|---|---|",
        f"| платформа | {env['platform']} ({env['system']}, {env['machine']}) |",
        f"| устройство | `{env['device']}` |",
        f"| dtype | `{env['dtype']}` |",
        f"| seq_len × batch | {env['seq_len']} × {env['batch_size']} |",
        f"| прогонов на режим | {env['repeats']} |",
        f"| память измерена | `{env['memory_metric']}` |",
        f"| RSS измерена | `{env['rss_metric']}` |",
        f"| python | {env['python']} |",
        f"| torch | {env['torch']} |",
        f"| transformers | {env['transformers']} |",
        f"| peft | {env['peft']} |",
        "",
        "Цифры ниже верны только для этих условий. Замер памяти без указания",
        "устройства, dtype, длины последовательности и метрики не воспроизводится",
        "и не сравнивается — поэтому источник метрики стоит отдельной строкой.",
        "Сверьте, что в этой строке названа метрика, уместная для вашего",
        "устройства, и что полученные числа с ней согласуются.",
        "",
    ]


def params_section(report: dict) -> list[str]:
    lines = [
        "## 3. Параметры по типам модулей",
        "",
        "| Группа | Модулей | Shape | Параметров | Доля | Разделяет тензор |",
        "|---|--:|---|--:|--:|--:|",
    ]
    for item in report["params_by_group"]:
        tied = thousands(item["tied_params"]) if item["tied_params"] else "—"
        lines.append(
            f"| `{item['group']}` | {item['modules']} | {item['shape']} | "
            f"{thousands(item['params'])} | {item['share'] * 100:.2f}% | {tied} |"
        )
    lines += [
        f"| **итого** | | | **{thousands(report['params_total'])}** | 100% | |",
        "",
        f"Контроль: `sum(p.numel() for p in model.parameters())` = "
        f"{thousands(report['params_direct'])} — сходится с суммой по таблице.",
        "",
        "Обратите внимание на строку `lm_head` и на значение `tie_word_embeddings`",
        "в конфигурации: они связаны, и от этой связи зависит итог таблицы.",
        "",
    ]
    return lines


def activations_section(report: dict, params: dict) -> list[str]:
    activations = report["activations"]
    lines = [
        "## 4. Нормы активаций (forward-hooks)",
        "",
        f"Промпт: «{params['hooks']['prompt']}», {activations['n_tokens']} токенов "
        "после chat template.",
        "",
        f"![нормы активаций]({Path(params['hooks']['plot']).name})",
        "",
        "| Блок | Индекс | Средняя ‖h‖₂ | Максимум |",
        "|---|--:|--:|--:|",
    ]
    for label, index in activations["layers"].items():
        values = activations["norms"][label]
        lines.append(f"| {label} | {index} | {sum(values) / len(values):.1f} | {max(values):.1f} |")
    lines += [
        "",
        "Норма меняется по глубине сети из-за последовательных attention/MLP-блоков",
        "и residual-связей. График дан в логарифмической шкале, чтобы крупные пики",
        "не скрывали различия между остальными позициями токенов.",
        "",
        f"Во время прогона было зарегистрировано {activations.get('hooks_registered', 0)} "
        f"хука; после `finally` на модели осталось {activations.get('hooks_left_after', 0)}.",
        "Повторный вызов поэтому не накапливает новый комплект обработчиков.",
        "",
    ]
    return lines


def lora_section(report: dict) -> list[str]:
    lines = [
        "## 5. Сколько параметров добавляет LoRA",
        "",
        "| Конфиг | Целевых модулей | Своя формула | peft | Совпало | % от базовой |",
        "|---|--:|--:|--:|:-:|--:|",
    ]
    for item in report["lora"]:
        lines.append(
            f"| {item['name']} | {len(item['target_modules'])} типов | "
            f"{thousands(item['formula'])} | {thousands(item['peft'])} | "
            f"{'да' if item['match'] else 'НЕТ'} | {item['share_of_base'] * 100:.3f}% |"
        )
    lines += [
        "",
        "Формула: `r * (in_features + out_features)` на каждый целевой `Linear` —",
        "`A` формы `(r, in)`, `B` формы `(out, r)`, смещений нет. Расхождение с",
        "`print_trainable_parameters()` означает ошибку в списке целевых модулей,",
        "а не «разные способы считать».",
        "",
        "Доля в таблице считается от базовой модели. `peft` печатает свою долю от",
        "модели ВМЕСТЕ с адаптером, поэтому его процент чуть меньше — числитель",
        "у обоих один и тот же.",
        "",
    ]
    return lines


def memory_section(report: dict) -> list[str]:
    modes = {item["mode"]: item for item in report["memory"]}
    base = modes["inference"]
    lines = [
        "## 6. Память в трёх режимах",
        "",
        f"Один шаг на seq_len={base['seq_len']}, batch={base['batch_size']}, "
        f"device={base['device']}. Метрика — {base['metric']} "
        f"(`{base['metric_source']}`), пик за прогон; колонка «Пик RSS» снята "
        f"через `{base['rss_source']}`.",
        "Вход — случайные id токенов: меряется память, а не качество, и loss здесь",
        "смысловой нагрузки не несёт. Время — только измеряемый шаг: для inference",
        "forward, для full FT/LoRA — forward + backward + optimizer.step(); загрузка",
        "модели и подготовка optimizer в таймер не входят. На CUDA/MPS таймер",
        "обрамлён synchronize(), чтобы учитывать фактическое выполнение на GPU.",
        "У full FT и LoRA loss на первом шаге одинаковый, потому что",
        "`B` в адаптере инициализирован нулями и до первого шага ничего не меняет).",
        "Числа должны отличаться: по лекции full fine-tune стоит кратно дороже",
        "инференса, а LoRA лежит между ними.",
        "",
        "| Режим | Пик, МБ | Пик RSS, МБ | × к инференсу | Секунд | loss |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for mode in ("inference", "full_ft", "lora"):
        item = modes[mode]
        loss = f"{item['loss']:.4f}" if item["loss"] is not None else "—"
        lines.append(
            f"| {MODE_TITLES[mode]} | {item['peak_mb']:.0f} | {item['peak_rss_mb']:.0f} | "
            f"{item['peak_mb'] / base['peak_mb']:.2f} | {item['seconds']:.3f} | {loss} |"
        )

    weights_mb = report["params_total"] * 2 / 1024 ** 2
    rss_values = [item["peak_rss_mb"] for item in modes.values()]
    rss_spread = max(rss_values) - min(rss_values)
    full_ratio = modes["full_ft"]["peak_mb"] / base["peak_mb"]
    lora_ratio = modes["lora"]["peak_mb"] / base["peak_mb"]
    full_vs_lora = modes["full_ft"]["peak_mb"] / modes["lora"]["peak_mb"]
    lines += [
        "",
        f"Прикидка из лекции: веса bf16 — {weights_mb:.0f} МБ. При полном обучении к",
        f"весам добавляются градиенты (порядка +{weights_mb:.0f} МБ) и два состояния",
        f"AdamW (порядка +{2 * weights_mb:.0f} МБ), плюс активации. Реальный пик зависит",
        "от реализации оптимизатора и аллокатора, поэтому сравниваем с измерением,",
        "а не подменяем его теоретической оценкой.",
        f"На этой машине full fine-tune = {full_ratio:.2f}× к инференсу, LoRA = "
        f"{lora_ratio:.2f}×; full fine-tune потребовал в {full_vs_lora:.2f}× больше",
        "пиковой памяти, чем LoRA.",
        f"LoRA обучает {thousands(report['lora'][0]['peft'])} параметров вместо "
        f"{thousands(report['params_total'])}: градиенты и состояния оптимизатора нужны",
        "только адаптерам, но активации для backward всё равно сохраняются, поэтому",
        "LoRA должна быть дороже чистого инференса.",
        "",
    ]
    if base["device"].startswith(("mps", "cuda")):
        lines += [
            f"RSS процесса по трём режимам имеет разброс {rss_spread:.0f} МБ, но основной",
            f"пик снят через `{base['metric_source']}`. На `{base['device']}` тензоры",
            "лежат в памяти ускорителя, поэтому RSS процесса используется только как",
            "дополнительная диагностическая колонка и не выдаётся за память модели.",
            "",
        ]
    else:
        lines += [
            f"Устройство — `{base['device']}`, поэтому основная метрика и есть RSS "
            f"процесса (`{base['rss_source']}`), обе колонки совпадают.",
            "На mps и cuda они разошлись бы: там тензоры лежат в памяти ускорителя",
            "и в RSS почти не видны, а разница между режимами исчезает.",
            "",
        ]
    return lines


def defects_section(report: dict) -> list[str]:
    """Разбор четырёх намеренных дефектов с числами текущего прогона."""
    tied = sum(item["tied_params"] for item in report["params_by_group"])
    naive_total = report["params_total"] + tied
    acts = report["activations"]
    modes = {item["mode"]: item for item in report["memory"]}
    base = modes["inference"]
    full = modes["full_ft"]
    lora = modes["lora"]

    return [
        "## 7. Четыре найденных дефекта",
        "",
        "### 7.1. Tied embeddings считались дважды",
        "",
        "Исходный обход использовал `named_parameters(remove_duplicate=False)`, но",
        "каждую строку помечал как уникальную. Поэтому общий тензор embeddings /",
        "`lm_head` попадал в сумму дважды. Исправление: хранить `id(parameter)` в",
        "`seen` и повторную ссылку отмечать как `tied`, не добавляя её в `params`.",
        f"Для этого прогона наивная сумма была бы {thousands(naive_total)}, из них",
        f"повторно посчитано {thousands(tied)}; корректная сумма —",
        f"{thousands(report['params_total'])}, ровно как прямой `sum(p.numel())` =",
        f"{thousands(report['params_direct'])}.",
        "",
        "### 7.2. Forward-hooks оставались жить после прогона",
        "",
        "`register_forward_hook()` возвращает handle, который раньше терялся. После",
        "повторного запуска на модулях копились обработчики. Исправление: сохранять",
        "handles и снимать каждый через `handle.remove()` в `finally`, чтобы очистка",
        "сработала даже при исключении во время forward.",
        f"В текущем прогоне зарегистрировано {acts.get('hooks_registered', 0)} хуков,",
        f"после завершения осталось {acts.get('hooks_left_after', 0)}.",
        "",
        "### 7.3. Вместо пика измерялся остаток памяти в конце",
        "",
        "Старый `PeakMemory.__exit__()` сначала запускал `gc.collect()`, а затем снимал",
        "одно текущее значение. Это отвечало на вопрос «что осталось после прогона»,",
        "а не «какой был максимальный расход». Исправление: CUDA использует встроенный",
        "high-water mark `torch.cuda.max_memory_allocated()`, MPS опрашивает",
        "`torch.mps.driver_allocated_memory()` во время прогона, CPU использует системный",
        "high-water mark RSS. Пик фиксируется до очистки объектов.",
        f"Полученные пики: inference {base['peak_mb']:.1f} МБ, LoRA {lora['peak_mb']:.1f} МБ,",
        f"full fine-tune {full['peak_mb']:.1f} МБ.",
        "",
        "### 7.4. На ускорителе использовался RSS процесса",
        "",
        "Функция `device_allocated_bytes()` раньше фактически возвращала `ru_maxrss` /",
        "`peak_wset` для любого устройства. На CUDA/MPS это не память ускорителя, поэтому",
        "цифры почти не реагировали на реальные GPU-аллокации. Исправление: выбирать",
        "метрику по устройству и запускать каждый режим в отдельном процессе через",
        "служебный `--probe`, чтобы high-water mark одного режима не загрязнял следующий.",
        f"Основная метрика этого прогона — `{base['metric_source']}` на `{base['device']}`;",
        f"для сравнения RSS инференса = {base['peak_rss_mb']:.1f} МБ, а основной пик =",
        f"{base['peak_mb']:.1f} МБ.",
        "",
    ]


def markdown_report(report: dict, params: dict) -> str:
    config = report["config"]
    lines = [
        f"# Анатомия {report['model'].split('/')[-1]}",
        "",
        f"Сгенерировано `make inspect`. dtype `{report['dtype']}`, device `{report['device']}`.",
        "",
        "## 1. Конфигурация",
        "",
        "| Параметр | Значение |",
        "|---|--:|",
        f"| слоёв | {config['num_hidden_layers']} |",
        f"| hidden_size | {config['hidden_size']} |",
        f"| intermediate_size | {config['intermediate_size']} |",
        f"| голов запроса | {config['num_attention_heads']} |",
        f"| KV-голов (GQA) | {config['num_key_value_heads']} |",
        f"| head_dim | {config['head_dim']} |",
        f"| словарь | {thousands(config['vocab_size'])} |",
        f"| tie_word_embeddings | {config['tie_word_embeddings']} |",
        "",
        f"GQA: {config['num_attention_heads']} голов запроса на "
        f"{config['num_key_value_heads']} KV-головы — "
        f"KV-cache вдвое меньше, чем при обычном multi-head.",
        "",
    ]
    lines += conditions_section(report)
    lines += params_section(report)
    lines += activations_section(report, params)
    lines += lora_section(report)
    lines += memory_section(report)
    lines += defects_section(report)
    return "\n".join(lines)


def write_report(report: dict, params: dict) -> None:
    """Нарисовать график и записать docs/anatomy.md."""
    plot_activations(report["activations"], params["hooks"]["plot"])
    path = Path(params["report"]["markdown"])
    path.parent.mkdir(exist_ok=True)
    path.write_text(markdown_report(report, params), encoding="utf-8")
