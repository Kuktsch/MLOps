import json
from pathlib import Path

from src.config import load_params


def load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Нет {path} — сначала make train")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    params = load_params()
    mdir = Path(params["paths"]["metrics"])
    all_m = load(mdir / "train_all_layers.json")
    freeze_m = load(mdir / "train_freeze14.json")
    lines = [
        "# HW5 — пять намеренных дефектов",
        "",
        f"Эксперимент выполнен в сокращённом режиме: `max_steps={all_m.get('max_steps')}`, использовано {all_m.get('train_examples_seen', '?')} из {all_m.get('available_train_examples', '?')} train-примеров и {all_m.get('val_examples', '?')} val-примеров.",
        "",
        "## 1. Валидация не считалась",
        "",
        "**Было:** цикл обучения сохранял только train loss, поэтому нельзя было понять, стал ли адаптер лучше базовой модели и не переобучается ли он.",
        "",
        "**Исправлено:** val loss считается до первого шага, затем через заданный интервал и в конце обучения. Для быстрого эксперимента используется фиксированное подмножество val; среднее взвешивается по числу supervised-токенов.",
        "",
        f"**Подтверждение:** для `all_layers` использовано **{all_m.get('val_examples', '?')}** val-примеров; loss изменился с **{all_m['base_val_loss']:.4f}** до **{all_m['final_val_loss']:.4f}**; записано **{len(all_m['curve_val'])}** точек.",
        "",
        "## 2. Learning rate был завышен",
        "",
        "**Было:** `lr=1e-2` давал слишком большой шаг оптимизатора. Обучение формально продолжалось, но такая настройка могла ухудшить модель относительно базы.",
        "",
        "**Исправлено:** learning rate уменьшен до `2e-4`; качество контролируется по независимому val loss, а не только по падению train loss.",
        "",
        f"**Подтверждение:** train loss `all_layers` идёт от **{all_m['curve_train'][0][1]:.4f}** на первом шаге к **{all_m['curve_train'][-1][1]:.4f}** на последнем, а val заканчивается ниже исходного: **{all_m['final_val_loss']:.4f} < {all_m['base_val_loss']:.4f}**.",
        "",
        "## 3. freeze14 не замораживал нижние слои",
        "",
        "**Было:** параметр `freeze_first` передавался в функцию конфигурации LoRA, но не влиял на создаваемые адаптеры. Оба эксперимента фактически обучали одни и те же слои.",
        "",
        "**Исправлено:** для `freeze14` в `layers_to_transform` передаются только слои 14–27; вариант `all_layers` по-прежнему использует все слои.",
        "",
        f"**Подтверждение:** обучаемых параметров стало **{freeze_m['trainable_params']:,}** вместо **{all_m['trainable_params']:,}**; время чистого обучения — **{freeze_m['seconds']:.1f} с** против **{all_m['seconds']:.1f} с**, пик памяти — **{freeze_m['peak_memory_mb']:.1f} МБ** против **{all_m['peak_memory_mb']:.1f} МБ**.",
        "",
        "## 4. Папка адаптера была непереносимой",
        "",
        "**Было:** сохранялись только веса и конфигурация LoRA, а `compare.py` заново загружал токенизатор по имени базовой модели. На другой машине папки адаптера было недостаточно.",
        "",
        "**Исправлено:** токенизатор вместе с chat template сохраняется через `save_pretrained` в ту же папку, а сравнение загружает его непосредственно из `adapter_dir`.",
        "",
        f"**Подтверждение:** папка `all_layers` занимает **{all_m['adapter_size_mb']:.2f} МБ** и содержит собственный `tokenizer_config.json`; проверка переносимости дополнительно запускает её офлайн и сравнивает ответы дословно.",
        "",
        "## 5. Seed не применялся",
        "",
        "**Было:** значение `train.seed` присутствовало в конфигурации, но перед созданием модели и LoRA не вызывалась функция фиксации генераторов случайных чисел. Инициализация LoRA и dropout могли отличаться между запусками.",
        "",
        "**Исправлено:** `set_seed` вызывается до загрузки модели и создания адаптеров; порядок train-примеров также строится детерминированно из того же seed.",
        "",
        f"**Подтверждение:** основной прогон записан с `seed={all_m['seed']}`. `make check` отдельно выполняет два трёхшаговых обучения с тем же конфигом и требует полного совпадения `curve_train`.",
        "",
        "## Сравнение двух вариантов",
        "",
        "| вариант | обучаемых параметров | val до | val после | время | пик памяти |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| all_layers | {all_m['trainable_params']:,} | {all_m['base_val_loss']:.4f} | {all_m['final_val_loss']:.4f} | {all_m['seconds']:.1f} с | {all_m['peak_memory_mb']:.1f} МБ |",
        f"| freeze14 | {freeze_m['trainable_params']:,} | {freeze_m['base_val_loss']:.4f} | {freeze_m['final_val_loss']:.4f} | {freeze_m['seconds']:.1f} с | {freeze_m['peak_memory_mb']:.1f} МБ |",
        "",
    ]
    out = Path("docs/defects.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
