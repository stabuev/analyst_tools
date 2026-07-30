# JSON и вложенные структуры

> Нормализация JSON начинается с выбора grain, а не с команды flatten.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 05/02  
**Время:** ~75 минут  
**Результат:** нормализует вложенные объекты и массивы в объявленный grain и обнаруживает
изменение схемы без потери сырого JSON.

## Цели обучения

- Отличать объект, массив и скаляр и читать вложенное значение по полному пути.
- Разделять один JSON-документ на родительскую и дочернюю таблицы с разным grain.
- Не смешивать отсутствующий путь, явный `null` и пустой массив.
- Строго разбирать raw bytes и сохранять их SHA-256 до преобразований.
- Обнаруживать изменения путей, типов, обязательности и ключей до публикации таблиц.

## Как этот урок продолжает маршрут

В фазах 03 и 04 вы уже задавали grain таблицы и проверяли уникальность ключа. В уроках
05/01 и 05/02 источник перестал быть «просто файлом»: у CSV появился диалект, у Excel —
лист и диапазон. JSON добавляет новую сложность: один документ может одновременно
содержать несколько единиц наблюдения.

Здесь вы работаете с уже сохраненным ответом API. В 05/04 научитесь безопасно получать
эти raw bytes по HTTP, а в 05/11 — атомарно обновлять кеш и manifest. Сейчас граница уже
строгая: невалидный документ можно исследовать, но из него нельзя поставить
нормализованные таблицы.

## Проблема

Поставщик событий возвращает один документ:

```json
{
  "exported_at": "2026-05-06T00:00:00Z",
  "events": [
    {
      "event_id": "E5001",
      "occurred_at": "2026-05-01T10:00:00Z",
      "user": {"id": "U001"},
      "context": {
        "device": {"os": "ios"},
        "screen": "checkout"
      },
      "items": [
        {"product_id": "P01", "quantity": 1, "price": 1000.0},
        {"product_id": "P02", "quantity": 1, "price": 200.5}
      ]
    }
  ]
}
```

Здесь есть три уровня:

- envelope всего экспорта с `exported_at`;
- события — по одной записи на `event_id`;
- позиции — от нуля до нескольких записей внутри события.

Если вызвать общий flatten без решения о grain, `items` либо останется списком внутри
ячейки, либо размножит строки события. Оба варианта могут выглядеть правдоподобно. Через
неделю источник добавит `schema_version`, пропустит обязательный путь или пришлет
`price: "12.995"`. Молчаливое приведение скроет изменение контракта.

## Концепция

### 1. JSON — дерево значений, а не таблица

Объект содержит пары ключ-значение, массив — упорядоченную последовательность, а листья
могут быть строкой, числом, `true`/`false` или `null`. Путь
`context.device.os` означает последовательный спуск по объектам. Он ничего не говорит о
типе, обязательности или grain — это добавляет контракт.

Три похожих состояния имеют разный смысл:

| Фрагмент | Что известно |
|---|---|
| `"os": null` | путь присутствует, значение явно неизвестно |
| нет ключа `os` | структура не соответствует обязательному пути |
| `"items": []` | массив присутствует, у события нет позиций |

Поэтому resolver возвращает специальный маркер для отсутствующего пути, а не тот же
`None`, который представляет JSON `null`.

### 2. Один документ превращается в две таблицы

Контракт объявляет две единицы наблюдения:

| Таблица | Grain | Что происходит при пустом `items` |
|---|---|---|
| `events` | `event_id` | событие остается |
| `items` | `event_id, item_position` | дочерняя строка не создается |

Для `E5001` две позиции получают ключи `("E5001", 1)` и `("E5001", 2)`.
`item_position` — номер появления в исходном массиве, а не идентификатор товара. Если
источник переставит элементы, позиционный ключ изменится. Для обновляемого каталога
понадобился бы устойчивый business key, но в этом снимке позиция честно описывает
наблюдаемое в документе.

После нормализации ключ родителя должен входить в каждую дочернюю строку. Проверить нужно
обе гипотезы grain: отсутствие `null` и дубликатов в `event_id`, затем то же для пары
`event_id, item_position`.

### 3. Контракт покрывает весь документ

`../data/json_contract.json` задает не только поля события:

```json
{
  "root_path": "events",
  "envelope_fields": {
    "exported_at": {
      "path": "exported_at",
      "type": "timestamp",
      "required": true,
      "nullable": false,
      "require_timezone": true
    }
  },
  "record_grain": ["event_id"],
  "array": {
    "path": "items",
    "required": true,
    "nullable": false,
    "position_field": "item_position",
    "grain": ["event_id", "item_position"]
  },
  "unknown_path_policy": "error"
}
```

У каждого поля отдельно объявлены:

- `path` — откуда читать значение;
- `type` — какой JSON/Python-тип допустим;
- `required` — обязан ли путь существовать;
- `nullable` — допустим ли явный `null`;
- для timestamp — обязателен ли UTC offset.

`allowed_paths` перечисляет полный документ: `exported_at`, `events`,
`events[].context.device.os`, `events[].items[].price` и промежуточные контейнеры. Иначе
изменение envelope осталось бы вне аудита.

### 4. Сначала строгий raw, затем преобразование

До `pandas` вход читается как bytes. SHA-256 относится именно к ним: повторное
форматирование JSON уже даст другой checksum. Декодирование требует UTF-8, а parser
отвергает две неоднозначности, которые стандартная конфигурация Python допускает:

- повторяющийся ключ объекта — непонятно, первое или последнее значение истинно;
- `NaN` и `Infinity` — это не числа грамматики JSON.

Только после успешного разбора начинаются извлечение полей и нормализация.

### 5. Drift — это несколько независимых проверок

Отчет разделяет причины:

- missing path — обязательного пути нет;
- null violation — путь есть, но `null` запрещен;
- type mismatch — значение другого типа или timestamp без offset;
- shape mismatch — вместо объекта или массива пришло другое значение;
- unknown path — появился неописанный путь;
- grain failure — ключ содержит `null` или повторяется.

Политика `unknown_path_policy: "error"` останавливает поставку. Режим `warn` допустим,
только если владелец данных сознательно разрешает добавочные поля: путь останется в
`warnings`, но не сделает отчет невалидным. Ошибки обязательности, типа и grain
предупреждением не становятся.

## Соберите это

### Шаг 1. Разберите исходные bytes без потери неоднозначностей

```python
raw = source.read_bytes()
payload = json.loads(
    raw.decode("utf-8", errors="strict"),
    object_pairs_hook=reject_duplicate_keys,
    parse_constant=reject_non_finite,
)
checksum = hashlib.sha256(raw).hexdigest()
```

`object_pairs_hook` видит пары до превращения в `dict`, поэтому может обнаружить
повторяющийся ключ. `parse_constant` не дает принять `NaN` как обычный `float`.

### Шаг 2. Отличите missing от null

```python
MISSING = object()


def get_path(value, path):
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current
```

Если `get_path(event, "context.device.os") is MISSING`, нарушена обязательность пути.
Если результат равен `None`, путь присутствует и проверяется правило `nullable`.

### Шаг 3. Создайте две строки разных grain

```python
parent_rows = []
child_rows = []

for event in payload["events"]:
    parent_rows.append(
        {
            "event_id": event["event_id"],
            "user_id": event["user"]["id"],
            "occurred_at": event["occurred_at"],
        }
    )
    for item_position, item in enumerate(event["items"], start=1):
        child_rows.append(
            {
                "event_id": event["event_id"],
                "item_position": item_position,
                **item,
            }
        )
```

Пустой массив выполняет ноль итераций: parent остается, фиктивного child не возникает.
После построения отдельно проверьте уникальность `event_id` и пары
`event_id, item_position`.

### Шаг 4. Инвентаризируйте пути

Рекурсивный обход добавляет путь каждого объекта, массива и листа. Массив помечается
суффиксом `[]`, поэтому `events[].items[].price` нельзя перепутать со скалярным
`events[].items.price`. Разность `observed_paths - allowed_paths` — список новых путей.

Запустите прозрачный пример из каталога урока:

```bash
uv run --locked python code/main.py
```

Он показывает checksum, envelope, ручную нормализацию и эквивалентные parent/child
таблицы через pandas.

## Используйте это

`pandas.json_normalize` полезен, когда grain уже выбран. Родителя и ребенка нужно
нормализовать раздельно:

```python
parent = pd.json_normalize(payload["events"], sep=".").drop(columns="items")

child = pd.json_normalize(
    payload["events"],
    record_path="items",
    meta=["event_id"],
    record_prefix="item.",
    meta_prefix="event.",
)
child.insert(
    1,
    "item_position",
    child.groupby("event.event_id").cumcount() + 1,
)
```

`record_path` выбирает массив дочерних записей, `meta` переносит ключ родителя, а prefixes
не дают перепутать происхождение столбцов. Но функция не знает ваш бизнес-grain, не
различает обязательный missing и разрешенный `null`, не проверяет весь envelope и сама
не решает, можно ли публиковать результат.

Самостоятельный артефакт объединяет эти решения:

```bash
uv run --locked python outputs/json_normalizer.py \
  --input ../data/tiny/events_nested.json \
  --contract ../data/json_contract.json \
  --output-dir delivery
```

Для валидного документа каталог `delivery/` содержит:

- `raw.json` — точную копию входных bytes;
- `events.jsonl` — строки grain `event_id`;
- `items.jsonl` — строки grain `event_id, item_position`;
- `report.json` — envelope, schema inventory, проверки, checksum и метаданные файлов.

Артефакт не зависит от переменных окружения или состояния `code/main.py`; ему нужны
только входной JSON, контракт и пустой выходной каталог.

## Сломайте это

Fixture `events_schema_drift.json` одновременно добавляет
`events[].context.app_version` и заменяет одно число `price` строкой:

```bash
uv run --locked python outputs/json_normalizer.py \
  --input ../data/tiny/events_schema_drift.json \
  --contract ../data/json_contract.json \
  --allow-failures
```

`--allow-failures` нужен только для просмотра отчета с exit code 0. Он не превращает
данные в валидные и не разрешает поставку. Если передать еще и `--output-dir`, артефакт
сообщит `"written": false` и не создаст нормализованные файлы.

Проверьте еще пять поломок:

1. Удалите `context.device.os`: это missing, даже если поле nullable.
2. Замените `"items": []` отсутствующим ключом: обязательный массив нарушен.
3. Добавьте top-level `schema_version`: путь должен попасть в drift.
4. Уберите `Z` у `occurred_at`: локальное время без offset не проходит контракт.
5. Продублируйте `event_id` в тексте JSON или подставьте `NaN`: строгий parser должен
   завершиться контролируемой ошибкой до нормализации.

## Проверьте это

Поведенческие тесты подтверждают не только happy path:

- три события создают три parent rows, а массивы — три child rows;
- `E5002` остается в events при пустом `items`;
- явный nullable `device_os: null` сохраняется, missing отклоняется;
- реализованный child grain совпадает с объявленным в контракте;
- дубликат parent key ломает и parent, и связанный child grain;
- top-level drift виден и может стать warning только по явной политике;
- строковая цена и timestamp без offset не приводятся молча;
- duplicate key, `NaN` и поврежденный UTF-8 дают контролируемую ошибку;
- invalid report не публикует `events.jsonl` и `items.jsonl`;
- raw copy сохраняет исходные bytes и SHA-256.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/json_normalizer.py` — одновременно quality gate и поставщик двух JSONL-таблиц.
Коды завершения являются частью интерфейса:

| Код | Значение |
|---:|---|
| `0` | документ валиден или невалидный отчет сознательно открыт через `--allow-failures` |
| `1` | JSON разобран, но данные не прошли контракт |
| `2` | вход, контракт или выход невозможно корректно обработать |

Публикация разрешена только при `summary.valid: true`. Перед записью артефакт повторно
читает input и сверяет checksum, требует пустой output directory и фиксирует размер и
SHA-256 каждого поставленного data-файла. Полная атомарная замена кеша остается задачей
05/11.

## Упражнения

1. Добавьте необязательный `schema_version` в envelope и сравните два осознанных решения:
   включить путь в новую версию контракта или временно перевести unknown paths в `warn`.
2. Представьте, что элемент получает устойчивый `line_item_id`. Измените child grain на
   `event_id, line_item_id` и добавьте тест на перестановку массива.
3. Добавьте второй дочерний массив `payments`. Сначала назовите его grain и связь с
   event, затем расширяйте нормализатор и тесты.

## Осознанные границы

- Урок обрабатывает один документ и один вложенный массив; универсальный JSON-to-table
  engine скрыл бы главное решение о grain.
- Позиция массива подходит снимку, но не обещает устойчивую идентичность между
  выгрузками.
- Контракт реализован небольшим учебным форматом; JSON Schema указан в чтении как
  следующий уровень формализации, а не спрятан внутри урока.
- Проверка checksum связывает raw и результат, но атомарная поставка и кеширование
  появятся в 05/11.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| JSON path | Имя будущего столбца | Маршрут к значению во вложенном документе |
| Flatten | Безопасная табличная форма | Преобразование, которое без выбранного grain может размножить строки |
| Parent grain | Число объектов | Ключ единицы наблюдения верхнего уровня |
| Child grain | `product_id` | Ключ дочерней единицы вместе со связью с родителем |
| Missing path | То же, что `null` | Структурно отсутствующий ключ |
| Schema drift | Другой порядок ключей | Изменение путей, типов, формы или обязательности |
| Raw layer | Лишняя копия | Неизменные входные bytes для аудита и replay |

## Дополнительное чтение

- [MDN: JSON](https://developer.mozilla.org/ru/docs/Glossary/JSON) — закрепите шесть типов значений JSON и отличие формата данных от синтаксиса объектов JavaScript.
- [Яндекс Образование: работа с текстовыми файлами и JSON](https://education.yandex.ru/handbook/python/article/potokovyj-vvodvyvod-rabota-s-tekstovymi-fajlami-json) — повторите базовый переход между JSON-файлом и типами Python; затем сравните простой `json.load` с более строгими hooks этого урока.
- [Postgres Professional: типы JSON](https://postgrespro.ru/docs/postgrespro/current/datatype-json?lang=ru-en) — посмотрите, какие различия между текстовым JSON и нормализованным представлением возникают уже на уровне СУБД, включая числа и повторяющиеся ключи.
- [Python: `json`](https://docs.python.org/3/library/json.html) — изучите `object_pairs_hook`, `parse_constant`, `allow_nan` и поведение parser за пределами строгой спецификации.
- [pandas: `json_normalize`](https://pandas.pydata.org/docs/reference/api/pandas.json_normalize.html) — разберите `record_path`, `meta`, prefixes и `errors`; отметьте, какие решения о grain функция оставляет вызывающему коду.
- [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) — проверьте требования к UTF-8,
  грамматике чисел и уникальности имен; это первичный ориентир для переносимого JSON.
- [ECMA-404](https://ecma-international.org/publications-and-standards/standards/ecma-404/) — сопоставьте краткую синтаксическую спецификацию с прикладным контрактом обязательности и типов из урока.
- [JSON Lines](https://jsonlines.org/) — сравните один вложенный документ и поток
  независимых JSON values; поймите, почему JSONL удобен для поставки табличных строк.
- [JSON Schema Core 2020-12](https://json-schema.org/draft/2020-12/json-schema-core.html) — изучите следующий уровень формализации схемы и отделите проверку документа от решения о нормализации в несколько grains.
- [W3C: Data on the Web Best Practices — provenance](https://www.w3.org/TR/dwbp/#dataProvenance) — свяжите сохранение raw bytes, checksum и отчета с более общей задачей происхождения и воспроизводимости данных.
