# Партиционирование наборов данных

> Хороший partition key сокращает чтение; плохой превращает набор данных в каталог мелких файлов.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 05/09  
**Время:** ~90 минут  
**Результат:** выбирает ключи партиционирования по паттерну чтения, проверяет pruning и
избегает мелких файлов и лишних разделов.

## Цели обучения

- Выбирать partition keys по filters и cardinality.
- Сравнивать candidate layouts до записи.
- Проверять pruning по Arrow fragments.
- Измерять small-file risk и checksums файлов.

## Проблема

Заказы раскладывают по `order_date/currency`. На tiny-наборе получается пять partitions
для пяти строк. На production это означает тысячи каталогов и маленьких файлов, хотя
типичный запрос фильтрует месяц и валюту.

## Концепция

Партиционирование выносит значения ключей в layout:

```text
order_month=2026-05/currency=RUB/part-0.parquet
```

Ключ полезен, если:

- часто присутствует в фильтрах;
- имеет умеренную cardinality;
- создает достаточно крупные файлы;
- понятен всем engines.

Hive-style layout позволяет восстановить partition columns из пути.

## Соберите это

До записи сравните число уникальных комбинаций:

```python
daily = {(date, currency) for ...}
monthly = {(date[:7], currency) for ...}
```

В учебном наборе day/currency дает пять partitions, month/currency — две.

```bash
uv run --locked python code/main.py
```

## Используйте это

PyArrow Dataset пишет Hive-layout:

```python
ds.write_dataset(
    table,
    output,
    format="parquet",
    partitioning=ds.partitioning(schema, flavor="hive"),
)
```

Pruning проверяется до materialization:

```python
selected = list(dataset.get_fragments(
    filter=ds.field("currency") == "EUR"
))
```

```bash
uv run --locked python outputs/dataset_builder.py \
  --input orders.parquet \
  --output-dir dataset \
  --partition-by order_month currency \
  --filter-currency EUR
```

## Сломайте это

1. Partition по `order_id`: файл почти на строку.
2. Partition по дню на редком наборе.
3. Filter по столбцу, которого нет в layout.
4. Смешение разных schemas в partitions.
5. Повторная запись поверх существующего каталога без policy.

## Проверьте это

- выбранный layout содержит две partitions вместо пяти дневных;
- все пять rows читаются как единый dataset;
- EUR filter выбирает один fragment из двух;
- одна tiny-partition отмечена как small file;
- каждый Parquet имеет checksum;
- DuckDB восстанавливает Hive columns и row count.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/dataset_builder.py` строит новый dataset только в отсутствующий каталог и
возвращает layout report: ключи, files, rows, small files, pruning и checksums.

## Упражнения

1. Сравните layouts month и month/currency на sample.
2. Добавьте compaction маленьких файлов.
3. Проверьте pruning через DuckDB `EXPLAIN ANALYZE`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Partition | Row group | Логическое разделение dataset, часто отраженное в paths |
| Hive layout | Формат Parquet | Соглашение `key=value` для каталогов |
| Pruning | Фильтрация после чтения | Исключение fragments до чтения |
| Small-file problem | Мало данных | Overhead множества слишком маленьких файлов |
| Cardinality | Число rows | Число уникальных значений или комбинаций ключа |

## Дополнительное чтение

- [PyArrow: Datasets](https://arrow.apache.org/docs/python/dataset.html) — изучите partitioning, discovery, filtering и writing.
- [PyArrow: HivePartitioning](https://arrow.apache.org/docs/python/generated/pyarrow.dataset.HivePartitioning.html) — разберите `key=value` parsing.
- [DuckDB: partitioned writes](https://duckdb.org/docs/stable/data/partitioning/partitioned_writes.html) — сравните управление layout из SQL engine.
- [Parquet: configurations](https://parquet.apache.org/docs/file-format/configurations/) — свяжите file, row group и page sizing с workload.
