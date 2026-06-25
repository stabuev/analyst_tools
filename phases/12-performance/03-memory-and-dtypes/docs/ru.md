# Память и типы данных

> Экономия памяти засчитывается только тогда, когда данные после нее означают то же самое.

**Тип:** Build
**Треки:** Data, ML
**Пререквизиты:** `12-performance/02-profiling`
**Время:** ~75 минут
**Результат:** оценивает footprint DataFrame, выбирает dtype policy для чисел, строк,
категорий, дат и nullable fields и проверяет, что экономия памяти не меняет
бизнес-смысл.

## Цели обучения

- Измерить память DataFrame по колонкам через deep memory report.
- Выбрать dtype policy по роли колонки, cardinality, диапазону и nullability.
- Безопасно уменьшить integer dtypes без переполнения и дробных значений.
- Применить `category` только к declared low-cardinality dimensions.
- Проверить, что деньги, пропуски, timestamp timezone и source grain не изменились.

## Проблема

После profiling команда видит: pipeline помещается в память на sample, но на рабочем
размере начинает давить ноутбук и CI runner. Простая реакция:

```python
df = df.astype("category")
df = df.astype("float32")
```

Так можно получить красивый memory reduction и тихо сломать данные:

- `order_id` стал category с неполным словарем и плохо переживает новые значения;
- `net_revenue_cents` потерял точность после float downcast;
- nullable integer превратился в `0`, хотя `NA` означал "не было первого заказа";
- timezone исчез из `week_start`;
- unsigned dtype переполнился на большем extract.

В performance-фазе dtype optimization - это schema decision, а не косметический
`astype`.

## Концепция

DataFrame хранит не только значения, но и их физическое представление. Один и тот же
бизнес-смысл можно хранить с разной стоимостью:

```text
object string -> string[pyarrow] или category
int64         -> UInt8 / UInt16 / UInt32 / Int32
float64 NA    -> nullable UInt16 / Int32
object bool   -> nullable boolean
object date   -> datetime64[*, UTC]
```

Но dtype нельзя выбирать только по минимальному размеру. Нужен policy:

1. role колонки: identifier, dimension, money, count, timestamp, nullable flag;
2. source dtype и memory bytes;
3. target dtype;
4. причина выбора;
5. semantic checks;
6. memory budget.

### Deep memory

`DataFrame.memory_usage(deep=True)` нужен, чтобы object/string колонки не выглядели
дешевле, чем они есть. Без `deep=True` Python objects часто недооцениваются, и вы
начинаете оптимизировать числовые колонки, хотя основная память сидит в строках.

### Category

`category` полезен, когда значений мало и они повторяются: `platform`, `region`, `plan`.
Для почти уникальных идентификаторов `order_id` или `user_id` category может стать
дороже и опаснее. В уроке категории разрешены только для declared domains.

### Nullable integers

Если целочисленная колонка содержит missing values, обычный NumPy integer не подходит.
Pandas nullable integer dtypes (`UInt8`, `UInt16`, `Int32` и т.д.) позволяют хранить
целые значения и `NA` без превращения колонки в float.

### Деньги

Деньги в уроке хранятся как integer cents. Никакой `float32` для `gross_revenue_cents`,
`refund_amount_cents` и `net_revenue_cents`: экономия памяти не стоит риска округления
или потери точной сверки.

## Соберите это

Артефакт урока строит план оптимизации для extract
`customer_revenue_health_weekly`. Вход нарочно похож на raw pandas DataFrame после CSV:
строки как object/string, даты строками, nullable integer как float/object.

### Шаг 1. Сгенерируйте вход

```python
frame = generate_revenue_extract(rows=5_000, seed=42)
```

Grain входа - `order_id, line_number`. Это еще не финальная недельная витрина, а
плоский extract для dtype policy.

### Шаг 2. Измерьте память

```python
baseline = dataframe_memory(frame)
```

В report попадают total bytes и список колонок с dtype, bytes и share. Сортировка по
bytes помогает начать ревью с самой дорогой колонки, а не с той, которая первой пришла в
голову.

### Шаг 3. Постройте policy

```python
policy = build_dtype_policy(frame)
```

Policy выбирает:

- identifiers -> `string[pyarrow]`;
- declared low-cardinality dimensions -> `category`;
- timestamps -> timezone-aware UTC datetime;
- nullable boolean -> `boolean`;
- non-negative counts -> самый маленький безопасный unsigned integer;
- signed money result -> самый маленький безопасный signed integer.

### Шаг 4. Примените policy

```python
optimized = apply_dtype_policy(frame, policy)
```

Перед cast проверяются unknown categories, дробные значения в integer columns,
отрицательные значения в unsigned columns и диапазоны через machine limits.

### Шаг 5. Проверьте смысл

```python
checks = semantic_checks(frame, optimized)
```

Минимальные checks:

- `order_id, line_number` уникален;
- row count сохранен;
- identifiers сохранены как labels;
- суммы money columns совпадают;
- money columns не стали float;
- missing counts сохранены;
- категории входят в declared domains;
- `week_start` остался UTC datetime.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/03-memory-and-dtypes/code/main.py
```

Запустите CLI-артефакт:

```bash
uv run --locked python phases/12-performance/03-memory-and-dtypes/outputs/dtype_policy.py \
  --rows 5000 \
  --seed 42 \
  --memory-budget-mb 4 \
  --output /tmp/dtype-policy.json
```

Report содержит:

- `baseline` - память исходного DataFrame по колонкам;
- `optimized` - память и dtypes после policy;
- `policy` - решение по каждой колонке;
- `semantic_checks` - доказательство, что смысл не изменился;
- `memory_budget` - можно ли shipping делать в заданном бюджете;
- `findings` - с какой колонки начать ревью.

## Сломайте это

### Добавьте неизвестную категорию

```python
frame.loc[0, "platform"] = "console"
```

`category` без контроля домена может превратить новое значение в missing или смешать
семантику. В уроке такой вход блокируется до cast.

### Сделайте integer дробным

```python
frame["support_ticket_count"] = frame["support_ticket_count"].astype("float64")
frame.loc[0, "support_ticket_count"] = 1.5
```

Это грязный CSV-like вход: колонка выглядит числовой, но уже не является count. Policy
обязан остановиться.

### Сделайте unsigned колонку отрицательной

```python
frame.loc[0, "gross_revenue_cents"] = -1
```

Отрицательный gross revenue ломает доменную модель. Нельзя просто выбрать signed dtype и
идти дальше: это уже data quality failure.

### Сожмите деньги во float

Если ради памяти привести копейки к `float32`, totals могут перестать сходиться на
больших данных. В уроке semantic checks требуют integer dtype и точную сумму.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/03-memory-and-dtypes/tests \
  -v
```

Что проверяют тесты:

- генерация входа воспроизводима;
- low-cardinality dimensions становятся category;
- identifiers не превращаются в category;
- optimized memory меньше baseline;
- nullable integer и nullable boolean сохраняют missing counts;
- money columns остаются integer и сохраняют totals;
- unknown categories, fractional counts и negative unsigned values блокируются;
- memory budget может заблокировать shipping;
- CLI пишет JSON и не печатает traceback на invalid input.

Полная проверка курса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Именованный артефакт урока:

```text
outputs/dtype_policy.py
```

Повторное использование:

```bash
python outputs/dtype_policy.py \
  --rows 5000 \
  --memory-budget-mb 4 \
  --output /tmp/dtype-policy.json
```

Перед передачей результата приложите:

```text
baseline_bytes: ...
optimized_bytes: ...
reduction_percent: ...
memory_budget: pass/watch/block
semantic_checks: all passed
policy changes:
  platform -> category
  first_paid_order_age_days -> UInt16
  net_revenue_cents -> Int32
known limits:
  memory_usage(deep=True) is DataFrame footprint, not full process RSS
```

## Упражнения

1. Уменьшите `memory_budget_mb` и найдите момент, где shipping становится `block`.
2. Добавьте новую low-cardinality колонку `device_family` и расширьте policy.
3. Измените генератор так, чтобы `order_id` имел всего 10 значений, и объясните, почему
   category для identifier все равно опасен без отдельного domain contract.
4. Добавьте check, который запрещает `float` для любых колонок с суффиксом `_cents`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| DataFrame footprint | "Это весь RSS процесса" | Память, которую pandas сообщает по данным и индексам; native/process memory шире |
| `deep=True` | "Всегда меняет данные" | Режим более глубокого учета object memory, без изменения DataFrame |
| Dtype policy | "Список astype-команд" | Обоснованное решение по типам с role, target dtype и semantic checks |
| Downcast | "Всегда безопасное уменьшение типа" | Смена типа на меньший диапазон, безопасная только после bounds checks |
| Category | "Лучший тип для любой строки" | Кодированное представление повторяющихся значений с явным доменом |
| Nullable integer | "То же самое, что float с NaN" | Integer extension dtype, который хранит целые значения и `NA` |
| Memory budget | "Желательная экономия" | Порог, который определяет, можно ли поставлять DataFrame в данном scenario |

## Дополнительное чтение

- [pandas: Scaling to large datasets](https://pandas.pydata.org/docs/user_guide/scale.html) - раздел про load less data, efficient dtypes, chunking и границы pandas in-memory подхода.
- [pandas.DataFrame.memory_usage](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.memory_usage.html) - API `memory_usage(index=True, deep=True)` и что именно возвращается по колонкам.
- [pandas: Categorical data](https://pandas.pydata.org/docs/user_guide/categorical.html) - когда category экономит память и почему comparisons зависят от совпадения categories.
- [pandas: Nullable integer data type](https://pandas.pydata.org/docs/user_guide/integer_na.html) - зачем явные `Int64`/`UInt16`-подобные dtypes нужны для целых значений с `NA`.
- [NumPy `iinfo`](https://numpy.org/doc/stable/reference/generated/numpy.iinfo.html) - machine limits для integer dtype, которые нужны перед безопасным downcast.
