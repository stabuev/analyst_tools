# Polars expressions

> В Polars производительный pipeline начинается не с другого синтаксиса DataFrame, а с
> переноса расчета в expressions, которые понимает query engine.

**Тип:** Build
**Треки:** Data, ML
**Пререквизиты:** `12-performance/06-duckdb-out-of-core`
**Время:** ~90 минут
**Результат:** переносит pipeline из pandas в Polars expressions, использует
select/with_columns/filter/group_by contexts, избегает row-wise Python UDF и проверяет
эквивалентность результата.

## Цели обучения

- Разобрать pandas pipeline на набор column expressions и result contract.
- Использовать Polars contexts: `select`, `with_columns`, `filter`, `group_by`.
- Заменить row-wise Python мышление на выражения `pl.col`, `pl.when`, `sum`, `rank`.
- Проверить, что Polars-результат совпадает с pandas control.
- Зафиксировать запрет на `map_elements`, `map_rows`, `iter_rows` и похожие обходы.

## Проблема

После DuckDB-урока команда понимает, что SQL engine полезен для Parquet и запросов больше
памяти. Но часть аналитического кода остается DataFrame-пайплайном: подготовка feature
tables, локальные проверки, быстрые продуктовые срезы.

Обычная миграция выглядит так:

```text
pandas было медленно -> перепишем на Polars построчно, а где неудобно, поставим apply.
```

Такой перенос часто оставляет главный bottleneck на месте. Polars силен, когда вы
выражаете расчет как набор expressions, а не когда гоняете Python-функцию по строкам.
Если внутри пайплайна появляются `iter_rows`, `map_elements` или строковый UDF, engine
теряет возможность выполнять работу векторно и оптимизировать выражения.

В этом уроке мы переносим один pandas-пайплайн в Polars eager API. Lazy execution и
optimized plan появятся в `12/08`; здесь цель уже практическая: научиться писать
выражения и проверять, что результат не изменился.

## Концепция

Polars expression - это декларация вычисления над колонками. Выражение само по себе еще
не результат:

```python
pl.col("gross_revenue_cents") - pl.col("refund_amount_cents")
```

Оно становится частью pipeline внутри context.

| Context | Что делает | Типичная ошибка |
|---|---|---|
| `select` | выбирает и вычисляет набор колонок результата | тащить все колонки дальше "на всякий случай" |
| `with_columns` | добавляет или заменяет колонки, сохраняя остальные | писать Python loop вместо выражения |
| `filter` | оставляет строки по boolean expression | материализовать mask в pandas до Polars |
| `group_by().agg` | считает агрегаты на заданном grain | считать агрегат через per-row UDF |

Ключевой сдвиг мышления:

```text
не "для каждой строки вызови функцию",
а "объяви, как новая колонка выражается через старые".
```

### Эквивалентность раньше скорости

Мы не сравниваем скорость в этом уроке. Сначала нужно доказать, что pandas и Polars
считают один и тот же бизнес-результат:

```text
input grain: один заказ
output grain: week_start, platform, region
metrics: orders, paid_orders, gross/refund/net revenue, support tickets
selection: top-3 region/platform cells по net revenue внутри каждой недели
```

Если результат отличается, performance-выигрыш не имеет смысла.

## Соберите это

Артефакт урока строит маленький extract `customer_revenue_health_weekly` и два pipeline:
pandas control и Polars expression implementation.

### Шаг 1. Сгенерируйте source rows

```python
frame = generate_customer_revenue_rows(rows=2_400, users=320, seed=42)
```

Входной grain - один заказ. В строках есть:

- ключи: `order_id`, `user_id`;
- измерения: `week_start`, `platform`, `region`, `plan`;
- денежные поля: `gross_revenue_cents`, `refund_amount_cents`;
- качество и фильтры: `status`, `support_ticket_count`, `is_test_user`.

### Шаг 2. Сформулируйте pandas control

```python
pandas_result = run_pandas_pipeline(frame)
```

Control делает привычные шаги:

1. проверяет входной контракт;
2. фильтрует недели `1..6` и исключает test users;
3. считает `net_revenue_cents` и `paid_order`;
4. агрегирует по `week_start, platform, region`;
5. добавляет derived metrics и rank внутри недели;
6. оставляет top-3 cells.

Это не "старый плохой код". Это эталон смысла, с которым должен совпасть новый engine.

### Шаг 3. Перенесите расчет в expressions

```python
polars_result = run_polars_expression_pipeline(frame)
```

Внутри Polars pipeline выглядит как цепочка contexts:

```python
(
    pl.from_pandas(frame)
    .select([...])
    .with_columns([...])
    .filter(...)
    .group_by(["week_start", "platform", "region"])
    .agg([...])
    .with_columns([...])
    .filter(...)
    .sort([...])
)
```

Выражения остаются columnar:

```python
(pl.col("gross_revenue_cents") - pl.col("refund_amount_cents")).alias("net_revenue_cents")

pl.when(pl.col("paid_orders") > 0)
  .then(pl.col("net_revenue_cents") // pl.col("paid_orders"))
  .otherwise(None)
```

Здесь нет Python-функции, которая получает одну строку. Это принципиально: расчет
остается видимым Polars engine.

### Шаг 4. Проверьте equivalence

```python
comparison = compare_outputs(pandas_result, polars_result)
```

Сравнение нормализует порядок строк, типы integer/nullable columns и проверяет весь
output contract. Хороший результат:

```text
equivalence.matches_pandas = true
equivalence.diff_preview = []
```

### Шаг 5. Проверьте, что это действительно expression pipeline

```python
audit = audit_artifact_expression_pipeline()
```

Audit читает source функции и проверяет:

```text
select > 0
with_columns > 0
filter > 0
group_by > 0
row_wise_python_detected = false
```

Это грубый статический guardrail, но он полезен: студент сразу видит, что
`map_elements(lambda ...)` - это не "почти то же самое", а отдельный риск.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/07-polars-expressions/code/main.py
```

Запустите CLI-артефакт и сохраните package:

```bash
uv run --locked python phases/12-performance/07-polars-expressions/outputs/polars_expression_pipeline.py \
  --rows 2400 \
  --users 320 \
  --seed 42 \
  --output-dir /tmp/polars-expression-pipeline
```

В директории появятся:

- `polars-output.csv` - результат Polars pipeline;
- `pandas-control.csv` - контрольный pandas-результат;
- `expression-audit.json` - проверка contexts и row-wise Python patterns;
- `report.json` - полный отчет.

Минимально хороший отчет:

```text
expression_audit.uses_polars_expressions = true
equivalence.matches_pandas = true
interpretation.safe_to_ship = true
```

## Сломайте это

### Добавьте `map_elements`

Например, замените `health_band` на Python lambda:

```python
pl.col("net_revenue_cents").map_elements(lambda value: "healthy" if value > 0 else "weak")
```

Статический audit должен поднять `row_wise_python_detected`. Иногда UDF неизбежен, но он
должен быть осознанным исключением с измерением стоимости.

### Уберите `select`

Если в начале pipeline оставить все колонки, вы переносите pandas-привычку "пусть едет
все". Для performance-пайплайна projection должна быть явной даже в eager API.

### Измените rank method

Поменяйте pandas `dense` rank на другой метод или Polars `rank(method="average")`.
Результат может отличиться только на tie cases. Именно такие мелочи и ловит equivalence
gate.

### Сравните только количество строк

Одинаковое число строк не доказывает одинаковый расчет. Нужно сравнить keys, metrics,
nullable derived fields и rank.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/07-polars-expressions/tests
```

Проверка артефакта:

```bash
uv run --locked python phases/12-performance/07-polars-expressions/outputs/polars_expression_pipeline.py \
  --rows 1200 \
  --users 160 \
  --output-dir /tmp/polars-expression-smoke
```

Контракт отчета:

- входной grain `order_id` уникален;
- Polars pipeline использует `select`, `with_columns`, `filter`, `group_by`;
- forbidden row-wise patterns отсутствуют;
- output grain `week_start, platform, region` уникален;
- Polars output совпадает с pandas control;
- отчет явно говорит, что lazy optimizer будет отдельной темой `12/08`.

## Поставьте результат

Именованный артефакт урока - CLI `polars-expression-pipeline`:

```bash
uv run --locked python phases/12-performance/07-polars-expressions/outputs/polars_expression_pipeline.py \
  --rows 2400 \
  --users 320 \
  --output-dir /tmp/polars-expression-pipeline
```

Его можно переиспользовать как шаблон переноса pandas-расчета:

1. оставьте pandas pipeline как control;
2. перепишите расчет через Polars expressions;
3. зафиксируйте contexts, которые должны быть в pipeline;
4. запретите row-wise Python escape hatches по умолчанию;
5. выпускайте результат только после equivalence gate.

## Упражнения

1. Добавьте измерение `plan` в output grain. Обновите pandas и Polars pipeline так, чтобы
   equivalence gate остался зеленым.
2. Добавьте derived metric `support_tickets_per_order_bp` через `pl.when().then()`.
   Проверьте nullable semantics при нулевом числе заказов.
3. Временно внесите `map_elements` в расчет `health_band` и убедитесь, что audit
   блокирует shipping. Затем верните expression-версию.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Expression | Просто другой способ написать lambda | Декларация вычисления над колонками, которую понимает Polars engine |
| Context | Любая строка method chaining | Место, где expression исполняется или добавляется к плану: `select`, `with_columns`, `filter`, `group_by` |
| `with_columns` | То же самое, что pandas row-wise `apply` | Добавление или замена колонок через column expressions |
| Row-wise UDF | Удобная мелочь без стоимости | Python escape hatch, который часто ломает vectorized execution и должен быть доказан измерением |
| Equivalence gate | Формальность после миграции | Обязательная проверка, что новый engine сохранил бизнес-результат |

## Дополнительное чтение

- [Polars: Expressions and contexts](https://docs.pola.rs/user-guide/concepts/expressions-and-contexts/) - основной текст урока: как expressions живут внутри `select`, `with_columns`, `filter` и `group_by`.
- [Polars: Column selections](https://docs.pola.rs/user-guide/expressions/column-selections/) - используйте как справочник по выбору колонок и selector-мышлению перед projection.
- [Polars: Migration from pandas](https://docs.pola.rs/user-guide/migration/pandas/) - прочитайте различия мышления между pandas и Polars при переносе pipeline.
- [Polars: User-defined Python functions](https://docs.pola.rs/user-guide/expressions/user-defined-python-functions/) - разберите предупреждения про `map_elements` и стоимость Python UDF.
