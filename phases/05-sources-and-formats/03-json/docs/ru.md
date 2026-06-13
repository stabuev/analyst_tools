# JSON и вложенные структуры

> Нормализация JSON начинается с выбора grain, а не с команды flatten.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 05/02  
**Время:** ~75 минут  
**Результат:** нормализует вложенные объекты и массивы в объявленный grain и обнаруживает
изменение схемы без потери сырого JSON.

## Цели обучения

- Различать вложенный объект и массив с отдельным grain.
- Извлекать поля по объявленным путям.
- Сохранять raw bytes и checksum до преобразований.
- Обнаруживать новые пути и несовместимые типы.

## Проблема

API возвращает события, пользователя внутри `user`, устройство внутри `context.device`, а
позиции заказа в массиве `items`. Обычный flatten превращает объекты в столбцы, но массив
остается Python-списком или размножает строки. Через неделю появляется
`context.app_version`, а `price` одного элемента приходит строкой.

Если исходный ответ не сохранен, невозможно доказать, была ли ошибка в источнике или в
нормализаторе.

## Концепция

У JSON нет обязательной табличной схемы. Контракт должен назвать:

- root-массив записей;
- пути скалярных полей;
- grain родительской таблицы;
- путь вложенного массива;
- grain дочерней таблицы;
- допустимые paths и типы.

В уроке создаются две таблицы:

| Таблица | Grain |
|---|---|
| events | `event_id` |
| items | `event_id, item_position` |

Пустой `items` сохраняет event, но не создает фиктивную позицию.

## Соберите это

Минимальный path resolver проходит словари по точкам:

```python
def get_path(value, path):
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
```

Для массива создайте отдельную строку на каждый элемент и добавьте ключ родителя и
позицию. Не используйте `product_id` как единственный ключ: один товар может встречаться
в разных событиях.

Параллельно обойдите дерево и соберите path inventory, обозначая массив как `items[]`.
Разность observed и allowed paths является сигналом изменения схемы.

```bash
uv run --locked python code/main.py
```

## Используйте это

`pandas.json_normalize` удобно разворачивает вложенные объекты:

```python
frame = pd.json_normalize(payload["events"], sep=".")
```

Но решение о `record_path`, metadata и grain все равно принимает аналитик. В примере
`items` намеренно остается списком, чтобы показать границу автоматического flatten.

Самостоятельный артефакт применяет контракт и может поставить delivery:

```bash
uv run --locked python outputs/json_normalizer.py \
  --input ../data/tiny/events_nested.json \
  --contract ../data/json_contract.json \
  --output-dir delivery
```

Каталог содержит неизменную `raw.json`, `events.jsonl`, `items.jsonl` и `report.json`.

## Сломайте это

В `events_schema_drift.json` добавлен path `context.app_version`, а одна цена стала
строкой. Оба изменения должны быть видимы отдельно:

```bash
uv run --locked python outputs/json_normalizer.py \
  --input ../data/tiny/events_schema_drift.json \
  --contract ../data/json_contract.json \
  --allow-failures
```

Новый необязательный path может быть принят новой версией контракта. Изменение типа нельзя
молча исправлять без правила источника.

## Проверьте это

- три события дают три parent rows;
- массивы дают три child rows;
- `E5002` остается в events при пустом items;
- child grain состоит из `event_id` и `item_position`;
- nullable `device_os` сохраняет `null`;
- drift сообщает `context.app_version`;
- строковый `price` проваливает type check;
- raw copy имеет тот же SHA-256.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/json_normalizer.py` является quality gate и поставщиком двух JSONL-таблиц. Он не
удаляет неизвестные данные: raw слой сохраняется побайтно, а отчет связывает его checksum
с нормализованным результатом.

## Упражнения

1. Добавьте второй вложенный массив и выберите для него grain.
2. Реализуйте режим `warn` для новых nullable paths.
3. Добавьте сравнение двух path inventories как schema diff.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| JSON path | Имя столбца | Маршрут к значению во вложенной структуре |
| Flatten | Безопасная табличная форма | Преобразование, которое может изменить grain |
| Parent grain | Число объектов | Ключ единицы наблюдения верхнего уровня |
| Schema drift | Другой порядок ключей | Изменение paths, типов или обязательности |
| Raw layer | Лишняя копия | Неизменный вход для аудита и replay |

## Дополнительное чтение

- [Python: `json`](https://docs.python.org/3/library/json.html) — изучите строгий разбор, типы Python и ограничения формата.
- [pandas: `json_normalize`](https://pandas.pydata.org/docs/reference/api/pandas.json_normalize.html) — разберите `record_path`, `meta`, `errors` и separator.
- [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) — отделите синтаксис JSON от прикладного договора о схеме и типах.
- [JSON Lines](https://jsonlines.org/) — сравните один большой документ и поток независимых записей для downstream-обработки.
