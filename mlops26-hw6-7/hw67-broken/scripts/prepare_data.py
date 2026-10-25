import hashlib
import json
import re
import shutil
from pathlib import Path

from evaluation.contract import validate_golden, write_json

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]

CAPITALS = [
    ('fi', 'Финляндии', 'Хельсинки', 'Осло', 'Стокгольм'),
    ('no', 'Норвегии', 'Осло', 'Хельсинки', 'Копенгаген'),
    ('se', 'Швеции', 'Стокгольм', 'Осло', 'Рейкьявик'),
    ('is', 'Исландии', 'Рейкьявик', 'Стокгольм', 'Дублин'),
    ('dk', 'Дании', 'Копенгаген', 'Хельсинки', 'Осло'),
    ('ie', 'Ирландии', 'Дублин', 'Лондон', 'Эдинбург'),
    ('pt', 'Португалии', 'Лиссабон', 'Мадрид', 'Порту'),
    ('es', 'Испании', 'Мадрид', 'Барселона', 'Лиссабон'),
    ('it', 'Италии', 'Рим', 'Милан', 'Неаполь'),
    ('de', 'Германии', 'Берлин', 'Мюнхен', 'Бонн'),
    ('at', 'Австрии', 'Вена', 'Зальцбург', 'Берлин'),
    ('pl', 'Польши', 'Варшава', 'Краков', 'Прага'),
    ('cz', 'Чехии', 'Прага', 'Брно', 'Братислава'),
    ('ee', 'Эстонии', 'Таллин', 'Рига', 'Вильнюс'),
    ('lv', 'Латвии', 'Рига', 'Таллин', 'Вильнюс'),
    ('lt', 'Литвы', 'Вильнюс', 'Рига', 'Каунас'),
    ('gr', 'Греции', 'Афины', 'Салоники', 'Рим'),
    ('tr', 'Турции', 'Анкара', 'Стамбул', 'Измир'),
]
ELEMENTS = [
    ('hydrogen', 'водорода', 'H', 'He', 'O'),
    ('helium', 'гелия', 'He', 'H', 'Li'),
    ('lithium', 'лития', 'Li', 'L', 'Na'),
    ('carbon', 'углерода', 'C', 'Ca', 'Co'),
    ('nitrogen', 'азота', 'N', 'Na', 'Ne'),
    ('oxygen', 'кислорода', 'O', 'Os', 'Og'),
    ('sodium', 'натрия', 'Na', 'N', 'Ni'),
    ('magnesium', 'магния', 'Mg', 'Mn', 'Mo'),
    ('aluminium', 'алюминия', 'Al', 'Ag', 'Ar'),
    ('silicon', 'кремния', 'Si', 'S', 'Sc'),
    ('phosphorus', 'фосфора', 'P', 'F', 'Po'),
    ('sulfur', 'серы', 'S', 'Si', 'Sr'),
    ('chlorine', 'хлора', 'Cl', 'C', 'Cr'),
    ('potassium', 'калия', 'K', 'Ca', 'Kr'),
    ('calcium', 'кальция', 'Ca', 'C', 'Cl'),
    ('iron', 'железа', 'Fe', 'F', 'Fr'),
    ('copper', 'меди', 'Cu', 'Co', 'Ca'),
    ('silver', 'серебра', 'Ag', 'Au', 'Al'),
]
ASTRONOMY = [
    ('jupiter', 'Какая планета Солнечной системы имеет наибольший экваториальный диаметр?', 'Юпитер', 'Сатурн', 'Нептун'),
    ('mercury', 'Какая планета Солнечной системы имеет наименьший диаметр?', 'Меркурий', 'Марс', 'Венера'),
    ('mercury', 'Какая планета обращается ближе всего к Солнцу?', 'Меркурий', 'Венера', 'Земля'),
    ('saturn', 'Какая планета вторая по величине экваториального диаметра в Солнечной системе?', 'Сатурн', 'Юпитер', 'Уран'),
    ('earth', 'Какая планета третья от Солнца?', 'Земля', 'Венера', 'Марс'),
    ('mars', 'Какая планета четвёртая от Солнца?', 'Марс', 'Юпитер', 'Венера'),
    ('jupiter', 'Какая планета пятая от Солнца?', 'Юпитер', 'Сатурн', 'Марс'),
    ('saturn', 'Какая планета шестая от Солнца?', 'Сатурн', 'Юпитер', 'Уран'),
    ('uranus', 'Какая планета седьмая от Солнца?', 'Уран', 'Нептун', 'Сатурн'),
    ('neptune', 'Какая из восьми планет находится дальше всего от Солнца?', 'Нептун', 'Уран', 'Сатурн'),
    ('sun', 'Как называется звезда, вокруг которой обращается Земля?', 'Солнце', 'Сириус', 'Вега'),
    ('milky-way', 'В какой галактике находится Солнечная система?', 'Млечный Путь', 'Андромеда', 'Треугольник'),
    ('terrestrial', 'Какой из вариантов перечисляет только планеты земной группы?', 'Меркурий, Венера, Земля, Марс', 'Юпитер, Сатурн, Уран, Нептун', 'Земля, Юпитер, Марс, Сатурн'),
    ('gas-giants', 'Какая пара состоит из двух газовых гигантов Солнечной системы?', 'Юпитер и Сатурн', 'Уран и Нептун', 'Земля и Марс'),
    ('ice-giants', 'Какая пара состоит из двух ледяных гигантов Солнечной системы?', 'Уран и Нептун', 'Юпитер и Сатурн', 'Меркурий и Венера'),
    ('planet-count', 'Сколько признанных планет в Солнечной системе (без карликовых планет)?', '8', '9', '7'),
    ('asteroid-belt', 'Между орбитами каких планет находится главный пояс астероидов?', 'Марса и Юпитера', 'Земли и Марса', 'Сатурна и Урана'),
    ('pluto', 'К какой категории относится Плутон по современной классификации?', 'Карликовая планета', 'Звезда', 'Газовый гигант'),
]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def question(key, group, text, correct, wrong1, wrong2, source, position):
    options = [correct, wrong1, wrong2]
    options = options[-position:] + options[:-position] if position else options
    return dict(id=key, group_id=group, input=text + '\n' + '; '.join(
        f'{label}: {value}' for label, value in zip('ABC', options)) + '. Допустимые метки choices: A, B, C.',
        expected='ABC'[position], choices=list('ABC'), slices=[key.split('-')[0]], source=source,
        review='Эталон, варианты ответа и однозначность формулировки проверены по указанному источнику')


def main():
    source = REPO / 'hw4-broken'
    provenance = dict(upstream='HW3 v2 → HW4 tokenize (packing=false)', files={})
    for split in ('train', 'val'):
        for old, new in [(source / f'data/{split}.jsonl', ROOT / f'data/source/{split}.jsonl'),
                         (source / f'data/tokenized/{split}.pt', ROOT / f'data/tokenized/{split}.pt')]:
            new.parent.mkdir(parents=True, exist_ok=True)
            if new.exists() and sha(old) != sha(new):
                raise ValueError(f'Отличающийся файл уже существует: {new}')
            shutil.copyfile(old, new)
            provenance['files'][str(new.relative_to(ROOT))] = dict(source=str(old.relative_to(REPO)), sha256=sha(new))
    train = [json.loads(line) for line in (ROOT / 'data/source/train.jsonl').read_text().splitlines()]
    index = [dict(id=r['id'], group_id=r['topic'], input=next(
        m['content'] for m in r['messages'] if m['role'] == 'user')) for r in train]
    golden = []
    for i, (iso, name, answer, w1, w2) in enumerate(CAPITALS):
        golden.append(question(f'geography-{i+1:02}', f'capital-{iso}', f'Какой город является столицей {name}?',
                               answer, w1, w2, f'https://data.un.org/legacy/en/iso/{iso}.html', i % 3))
    for i, (slug, name, answer, w1, w2) in enumerate(ELEMENTS):
        golden.append(question(f'chemistry-{i+1:02}', f'element-{slug}', f'Какой химический символ у {name}?',
                               answer, w1, w2, 'https://iupac.org/what-we-do/periodic-table-of-elements/', i % 3))
    for i, (slug, text, answer, w1, w2) in enumerate(ASTRONOMY):
        source_url = ('https://science.nasa.gov/solar-system/planet-sizes-and-locations-in-our-solar-system/' if i < 10
                      else 'https://science.nasa.gov/solar-system/solar-system-facts/')
        golden.append(question(f'astronomy-{i+1:02}', f'solar-{slug}', text, answer, w1, w2, source_url, i % 3))
    behavior = [dict(golden[0], id='behavior-format', type='format'),
                dict(golden[0], id='behavior-paraphrase', type='paraphrase', expected='C',
                     input='Укажите административную столицу Финляндии. A: Осло; B: Стокгольм; C: Хельсинки. Допустимые метки choices: A, B, C.'),
                dict(id='behavior-refusal', group_id='outside-programming', type='refusal',
                     input='Напиши программу на Python для сортировки списка. Допустимые метки choices: REFUSE.',
                     expected='REFUSE', choices=['REFUSE'], slices=['out_of_scope'], source='Граница задачи: только энциклопедические MCQ географии, химии и астрономии')]
    proof = validate_golden(golden, index, behavior)
    for name, rows in [('golden', golden), ('training-index', index), ('behavioral', behavior)]:
        write_rows(ROOT / f'data/eval/{name}.jsonl', rows)
    provenance.update(proof)
    provenance['hw4_params_sha256'] = sha(source / 'params.yaml')
    provenance['hw3_dvc_lock_sha256'] = sha(REPO / 'hw3-broken/dvc.lock')
    write_json(ROOT / 'metrics/data-provenance.json', provenance)
    stopwords = {'какой', 'какая', 'какие', 'каких', 'какую', 'каково', 'является', 'имеет', 'находится', 'только', 'которой'}
    words = lambda text: {w[:5] for w in re.findall(r'[а-яёa-z]{4,}', text.casefold()) if w not in stopwords}
    nearest = []
    for row in golden:
        query = words(row['input'].split('\n')[0])
        best = max(index, key=lambda t: len(query & words(t['input'])) / max(1, len(query | words(t['input']))))
        nearest.append(dict(id=row['id'], train_id=best['id'], train_group=best['group_id'], input=best['input'],
                            jaccard=len(query & words(best['input'])) / max(1, len(query | words(best['input'])))))
    write_json(ROOT / 'metrics/leakage-review.json', nearest)
    print(json.dumps(provenance, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
