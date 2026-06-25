# Projection и predicate pushdown

> Parquet ускоряет запрос не магией, а тем, что вы заранее сделали чтение
> ненужных колонок, файлов и row groups необязательным.

**Тип:** Case
**Треки:** Data, ML
**Пререквизиты:** `12-performance/03-memory-and-dtypes`
**Время:** ~75 минут
**Результат:** проектирует Parquet layout с row groups, partitions, statistics и
нужными колонками, измеряет projection/predicate pushdown и подтверждает его через
query plans.

## Цели обучения

- Объяснить, чем projection pushdown отличается от predicate pushdown.
- Спроектировать Parquet layout с partition columns, row groups и statistics.
- Измерить разницу между полным scan и scan с нужными колонками и фильтром.
- Проверить file pruning и row-group pruning по metadata.
- Подтвердить физический план через `EXPLAIN`, а результат - контрольным расчетом.

## Проблема

Команда хранит недельную витрину `customer_revenue_health_weekly` в Parquet. В BI и
batch scoring чаще всего нужен один week_start и несколько метрик:

```sql
SELECT platform, sum(net_revenue_cents), sum(paid_orders)
FROM customer_revenue_health_weekly
WHERE week_start = DATE '2026-02-02'
GROUP BY platform;
```

Если файл сделан как "один большой dump всех колонок", движок вынужден читать широкие
строковые payloads, все недели и row groups без отбора. Запрос все еще вернет правильное
число, но будет платить I/O и CPU за данные, которые не участвуют в ответе.

Performance-решение здесь не в том, чтобы после факта добавить еще один cache. Нужно
сделать layout, который позволяет движку не читать лишнее, а потом доказать это планом
запроса и metadata audit.

## Концепция

Parquet - columnar формат. Внутри файла данные хранятся по колонкам и row groups. Это
дает два главных рычага.

Projection pushdown - движок читает только колонки, нужные запросу. Если запросу нужны
`platform`, `paid_orders` и `net_revenue_cents`, широкие колонки вроде `raw_event_json`
не должны попадать в scan.

Predicate pushdown - движок применяет фильтр ближе к данным:

1. partition pruning отбрасывает файлы по пути, например
   `week_start=2026-02-02`;
2. row-group pruning использует min/max statistics внутри Parquet metadata;
3. scan возвращает только строки, которые прошли фильтр.

Эти механизмы работают только если layout помогает движку:

- partition column соответствует частому и селективному фильтру;
- row groups не слишком огромные и не слишком мелкие;
- данные внутри row groups имеют полезную локальность;
- statistics записаны при создании Parquet;
- запрос действительно выбирает узкий набор колонок.

Один прогон benchmark не доказывает "ускорение в N раз". Он доказывает форму чтения:
сколько колонок, файлов и row groups могло быть отброшено. Для стабильного сравнения
скорости используйте методологию из `12-performance/01-benchmarking`.

## Соберите это

Артефакт урока строит audit package для учебной витрины выручки. Он не скачивает внешние
данные: все строки генерируются воспроизводимо.

### Шаг 1. Создайте широкий extract

```python
frame = generate_revenue_rows(rows=4_800, seed=42)
```

В данных есть нужные для запроса колонки:

- `week_start`, `week_index`;
- `platform`;
- `paid_orders`, `net_revenue_cents`.

И есть колонки, которые делают projection заметным:

- `raw_event_json`;
- `debug_payload`;
- `support_notes`.

### Шаг 2. Запишите Parquet layout

```python
dataset_dir = write_parquet_layout(frame, output_dir, row_group_size=128)
```

Функция пишет Hive-partitioned dataset:

```text
dataset/
  week_start=2026-01-05/
    *.parquet
  week_start=2026-01-12/
    *.parquet
```

Параметры записи важны:

- `partition_cols=["week_start"]` дает file pruning по неделе;
- `row_group_size=128` делает несколько row groups внутри недельного файла;
- `write_statistics=True` сохраняет min/max metadata;
- `compression="zstd"` снижает физический размер без изменения запроса.

### Шаг 3. Прочитайте metadata

```python
layout = inspect_layout(
    dataset_dir,
    target_week="2026-02-02",
    target_week_index=4,
    required_columns=[
        "week_start",
        "week_index",
        "platform",
        "paid_orders",
        "net_revenue_cents",
    ],
    row_group_size=128,
)
```

Audit не доверяет обещаниям. Он открывает Parquet metadata и считает:

- сколько файлов в dataset;
- сколько partition values найдено;
- какие physical columns лежат в файлах;
- сколько файлов остается для target week;
- сколько row groups остается по statistics колонки `week_index`;
- есть ли row groups без min/max statistics.

### Шаг 4. Сравните полный scan и pushdown scan

```python
report = arrow_scan_measurements(
    dataset_dir,
    target_week="2026-02-02",
    target_week_index=4,
    required_columns=DEFAULT_REQUIRED_COLUMNS,
)
```

Полный scan читает все logical columns и все строки. Pushdown scan использует PyArrow
Dataset:

```python
dataset.to_table(
    columns=required_columns,
    filter=(
        (ds.field("week_start") == "2026-02-02")
        & (ds.field("week_index") == 4)
    ),
)
```

В отчете важно смотреть не только на время:

- `full_column_count` против `projected_column_count`;
- `full_scan_output_bytes` против `pushed_scan_output_bytes`;
- `full_rows` против `pushed_rows`;
- список omitted physical columns.

### Шаг 5. Подтвердите план и результат

```python
duckdb_report = duckdb_query_and_plan(
    dataset_dir,
    target_week="2026-02-02",
    target_week_index=4,
)
```

DuckDB читает тот же Parquet dataset через `read_parquet(..., hive_partitioning=true)`,
строит `EXPLAIN` и выполняет aggregation. Затем результат сверяется с pandas control.

Проверка считается готовой только если одновременно верны условия:

- projection оставила меньше колонок и меньше output bytes;
- partition pruning оставил только файлы target week;
- row-group statistics отбросили часть row groups;
- `EXPLAIN` показывает Parquet scan и фильтр по `week_index`;
- агрегаты DuckDB совпали с pandas control;
- отчет явно говорит, что это scan-shape audit, а не финальный speedup claim.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/04-parquet-pushdown/code/main.py
```

Запустите CLI-артефакт и сохраните audit package:

```bash
uv run --locked python phases/12-performance/04-parquet-pushdown/outputs/parquet_pushdown_audit.py \
  --rows 4800 \
  --seed 42 \
  --row-group-size 128 \
  --target-week 2026-02-02 \
  --output-dir /tmp/parquet-pushdown-audit
```

В директории появятся:

- `dataset/` - partitioned Parquet files;
- `report.json` - полный отчет;
- `parquet-layout.json` - компактный layout и pushdown audit;
- `query-plan.txt` - DuckDB physical plan.

Минимальная интерпретация:

```text
safe_to_ship = true
```

означает только то, что layout и запрос согласованы. Для production-решения все еще
нужны стабильные benchmark runs на реальном размере данных, лимиты по small files и
наблюдение в целевом engine.

## Сломайте это

### Уберите projection

Попросите `dataset.to_table()` без `columns=...`. Отчет должен показать, что широкие
payload columns снова попали в output.

### Выберите неподходящую partition column

Если partition сделать по `platform`, а запрос фильтрует `week_start`, движок не сможет
отбросить недельные файлы по пути. Это особенно больно для витрин, которые почти всегда
читаются по периоду.

### Запишите без statistics

Без min/max statistics row-group pruning превращается в догадку. Audit должен увидеть
`missing_statistics_count > 0` и запретить shipping.

### Сделайте слишком много мелких файлов

Partitioning по высококардинальной колонке создает small files. Даже если pruning
работает, overhead на metadata и открытие файлов может съесть пользу.

### Поверьте одному timing

Если один запуск стал быстрее, это еще не доказательство. OS cache, прогрев Python,
планировщик и соседние процессы легко меняют секунды. В этом уроке timing вторичен:
главное доказательство - scan shape и query plan.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/04-parquet-pushdown/tests
```

Проверка артефакта:

```bash
uv run --locked python phases/12-performance/04-parquet-pushdown/outputs/parquet_pushdown_audit.py \
  --rows 1200 \
  --output-dir /tmp/parquet-pushdown-audit
```

Контракт отчета:

- `projection.passed == true`;
- `predicate_pushdown.partition_pruning.passed == true`;
- `predicate_pushdown.row_group_statistics.passed == true`;
- `duckdb_plan.checks.parquet_scan_present == true`;
- `result_contract.passed == true`;
- `interpretation.safe_to_ship == true`.

## Поставьте результат

Именованный артефакт урока:

```text
outputs/parquet_pushdown_audit.py
```

Это CLI для ревью Parquet layout. Его можно использовать вне урока как шаблон:

1. замените генератор данных на свой source extract;
2. оставьте явный список required columns;
3. добавьте фильтры, которые реально использует ваш workload;
4. сохраните `report.json` и `query-plan.txt` рядом с performance review.

Для сдачи результата приложите:

- layout decision: partition columns, row-group size, compression, statistics;
- scan-shape evidence: columns/files/row groups до и после pushdown;
- query plan evidence;
- контрольную сверку результата;
- ограничения интерпретации.

## Упражнения

1. Поменяйте `target_week` на другую неделю и проверьте, что candidate files и row groups
   меняются ожидаемо.
2. Добавьте метрику `gross_revenue_cents` в required columns и объясните, как меняется
   projection.
3. Запишите dataset с `row_group_size=1000` и сравните, насколько хуже становится
   row-group pruning.
4. Сделайте partitioning по `region` вместо `week_start` и опишите, какой рабочий
   запрос от этого выиграет, а какой проиграет.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Projection pushdown | "Это просто SELECT меньшего числа колонок" | Физический scan читает только нужные колонки из columnar storage. |
| Predicate pushdown | "Фильтр применяется после чтения файла" | Фильтр передается в scan и может отбросить файлы, row groups или страницы раньше. |
| Partition pruning | "Partitioning всегда ускоряет" | Ускоряет только запросы, которые фильтруют по partition columns с достаточной селективностью. |
| Row group | "Это то же самое, что файл" | Внутренняя группа строк внутри Parquet file, у которой есть metadata и statistics. |
| Statistics | "Нужны только для оптимизатора SQL" | Min/max/null metadata позволяют не читать row groups, которые не могут пройти фильтр. |
| Query plan | "План нужен только DBA" | Для performance-audit план доказывает, что engine действительно использует scan и фильтры так, как вы ожидаете. |

## Дополнительное чтение

- [DuckDB Parquet support](https://duckdb.org/docs/current/data/parquet/overview) - прочитайте про `read_parquet`, projection/filter pushdown, Hive partitioning, row groups и compression.
- [DuckDB EXPLAIN](https://duckdb.org/docs/current/guides/meta/explain) - используйте для чтения physical plan и проверки, где применяются filters/projections.
- [Apache Arrow Parquet](https://arrow.apache.org/docs/python/parquet.html) - посмотрите, как PyArrow читает columns, metadata и row groups.
- [Apache Arrow Dataset](https://arrow.apache.org/docs/python/dataset.html) - разберите `to_table(columns=..., filter=...)` и Hive partitioning.
- [pandas.read_parquet](https://pandas.pydata.org/docs/reference/api/pandas.read_parquet.html) - проверьте параметры `columns` и `filters`, если ваш pipeline читает Parquet через pandas.
