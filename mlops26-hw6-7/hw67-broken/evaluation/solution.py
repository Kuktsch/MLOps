"""Строгая оценка меток и допуск без регрессий."""
import json
import math


def _index(items):
    if not isinstance(items, list) or not items:
        raise ValueError('Нужен непустой список примеров')
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Пример должен быть словарём')
        key = item.get('id')
        if not isinstance(key, str) or not key or key in result:
            raise ValueError('Нужны уникальные непустые строковые id')
        result[key] = item
    return result


def _summary(items):
    n = len(items)
    correct = sum(item['correct'] for item in items)
    valid = sum(item['valid'] for item in items)
    return dict(n=n, correct=correct, valid=valid,
                errors=sum(item['error'] is not None for item in items),
                accuracy=correct / n, format_rate=valid / n)


def _object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError('Повторяющиеся ключи JSON')
    return obj


def score(rows, outputs):
    """Верните overall, slices и per_item. Не удаляйте плохие ответы из знаменателя.

    Строгий ответ: JSON с единственным строковым полем answer из choices.
    outputs: [{id, raw, error, latency_seconds}, ...].
    В overall и каждом срезе: n, correct, valid, errors, accuracy, format_rate.
    В per_item: id, raw, parsed, valid, correct, error, slices.
    Несовпадающие/дублирующиеся id и пустой набор должны вызвать ValueError.
    """
    tasks, answers = _index(rows), _index(outputs)
    if tasks.keys() != answers.keys():
        raise ValueError('ID заданий и ответов различаются')
    per_item = []
    for key, row in tasks.items():
        choices, slices = row.get('choices'), row.get('slices')
        if (not isinstance(choices, list) or not choices or
                any(not isinstance(c, str) or not c for c in choices) or
                len(set(choices)) != len(choices) or row.get('expected') not in choices):
            raise ValueError('Некорректные choices/expected')
        if (not isinstance(slices, list) or not slices or
                any(not isinstance(s, str) or not s for s in slices) or len(set(slices)) != len(slices)):
            raise ValueError('Некорректные slices')
        output = answers[key]
        raw, error = output.get('raw'), output.get('error')
        if error is not None and (not isinstance(error, str) or not error):
            raise ValueError('error должен быть непустой строкой или null')
        parsed, valid = None, False
        if isinstance(raw, str) and error is None:
            try:
                value = json.loads(raw, object_pairs_hook=_object)
                if (isinstance(value, dict) and set(value) == {'answer'} and
                        isinstance(value['answer'], str) and value['answer'] in choices):
                    parsed, valid = value['answer'], True
            except (ValueError, RecursionError):
                pass
        per_item.append(dict(id=key, raw=raw, parsed=parsed, valid=valid,
                             correct=valid and parsed == row['expected'], error=error, slices=list(slices)))
    names = sorted({s for item in per_item for s in item['slices']})
    return dict(overall=_summary(per_item),
                slices={s: _summary([item for item in per_item if s in item['slices']]) for s in names},
                per_item=per_item)


def _validate_score(report):
    if not isinstance(report, dict):
        raise ValueError('Отсутствует отчёт')
    items = _index(report.get('per_item'))
    for item in items.values():
        if not {'raw', 'parsed', 'valid', 'correct', 'error', 'slices'} <= item.keys():
            raise ValueError('Неполный per_item')
        if type(item.get('valid')) is not bool or type(item.get('correct')) is not bool:
            raise ValueError('Некорректные флаги per_item')
        if (item['valid'] and (not isinstance(item['raw'], str) or not isinstance(item['parsed'], str)) or
                not item['valid'] and item['parsed'] is not None):
            raise ValueError('Несогласованные raw/parsed/valid')
        error = item.get('error')
        if ('error' not in item or error is not None and (not isinstance(error, str) or not error) or
                item['correct'] and not item['valid'] or error is not None and item['valid']):
            raise ValueError('Несогласованные per_item/error')
        slices = item.get('slices')
        if (not isinstance(slices, list) or not slices or
                any(not isinstance(s, str) or not s for s in slices) or len(set(slices)) != len(slices)):
            raise ValueError('Некорректные срезы per_item')
    names = {s for item in items.values() for s in item['slices']}
    if not isinstance(report.get('slices'), dict) or set(report['slices']) != names:
        raise ValueError('Срезы отчёта и per_item различаются')
    groups = [(report.get('overall'), list(items.values()))]
    groups += [(report['slices'][s], [i for i in items.values() if s in i['slices']]) for s in names]
    for metrics, group in groups:
        if not isinstance(metrics, dict):
            raise ValueError('Отсутствуют метрики')
        expected = _summary(group)
        for key in ('n', 'correct', 'valid', 'errors'):
            if type(metrics.get(key)) is not int or metrics[key] != expected[key]:
                raise ValueError(f'Counts не соответствуют per_item: {key}')
        for key in ('accuracy', 'format_rate'):
            value = metrics.get(key)
            if (type(value) not in (int, float) or not math.isfinite(value) or
                    not math.isclose(value, expected[key], rel_tol=0, abs_tol=1e-12)):
                raise ValueError(f'Метрика не соответствует counts: {key}')
    if report['overall']['errors']:
        raise ValueError('Есть ошибки генерации')
    return items


def quality_gate(baseline, candidate, critical_slices):
    """Верните {passed: True, ...} или вызовите ValueError с причиной отказа.

    Проверьте совместимость протокола/набора/baseline, метрики и counts,
    все id и срезы, общую accuracy/format_rate, критические срезы и behavior.
    Missing, NaN, пустой набор и ошибки генерации означают отказ.
    Пороги задаются до измерения; учебный допуск регрессии равен нулю.
    """
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError('Нужны два полных отчёта')
    for key in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
        if not isinstance(baseline.get(key), str) or not baseline[key] or baseline[key] != candidate.get(key):
            raise ValueError(f'Несовместимый или отсутствующий {key}')
    indexes, behaviors = [], []
    for report in (baseline, candidate):
        model = report.get('model')
        if (report.get('status') != 'complete' or not isinstance(model, dict) or
                not isinstance(model.get('kind'), str) or not model['kind']):
            raise ValueError('Отчёт неполный или отсутствует модель')
        indexes.append(_validate_score(report))
        if report['overall']['n'] < 50 or len(report['slices']) < 3:
            raise ValueError('Нужно минимум 50 golden-примеров и три среза')
        behaviors.append(_validate_score(report.get('behavioral')))
        if report['behavioral']['overall']['n'] < 3:
            raise ValueError('Нужно минимум три behavioral-кейса')
    for a, b in (indexes, behaviors):
        if a.keys() != b.keys() or any(set(a[k]['slices']) != set(b[k]['slices']) for k in a):
            raise ValueError('Различаются id или принадлежность срезам')
    if (not isinstance(critical_slices, list) or not critical_slices or
            any(not isinstance(s, str) or s not in baseline['slices'] for s in critical_slices)):
        raise ValueError('Критические срезы отсутствуют')
    for key in ('accuracy', 'format_rate'):
        if candidate['overall'][key] < baseline['overall'][key]:
            raise ValueError(f'Общая регрессия {key}')
    for name in critical_slices:
        if candidate['slices'][name]['accuracy'] < baseline['slices'][name]['accuracy']:
            raise ValueError(f'Регрессия критического среза {name}')
    behavior = candidate['behavioral']['overall']
    if behavior['correct'] != behavior['n'] or behavior['valid'] != behavior['n']:
        raise ValueError('Не все behavioral-кейсы кандидата пройдены')
    return dict(passed=True, protocol_sha256=candidate['protocol_sha256'],
                golden_sha256=candidate['golden_sha256'], critical_slices=list(critical_slices),
                baseline=baseline['model'], candidate=candidate['model'])
