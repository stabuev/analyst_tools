# Parquet и колоночное хранение

> Parquet переносит схему внутрь файла, но схема должна быть выбрана до записи.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 05/07  
**Время:** ~75 минут  
**Результат:** записывает и читает Parquet с явной схемой, nullable-типами и сжатием и
сравнивает его контракт с CSV.

## Цели обучения

- Различать текстовый CSV и типизированный Parquet.
- Строить Arrow schema с decimal, timestamp и nullable.
- Проверять metadata и roundtrip после записи.
- Не сводить выбор формата только к размеру tiny-файла.

## Проблема

CSV заказов каждый читатель типизирует по-своему. Один превращает amount во float, другой
теряет timezone, третий считает пустой comment строкой. Требуется reusable-файл для
аналитических движков.

## Концепция

Parquet хранит:

- физические и логические типы;
- column chunks внутри row groups;
- encoding и compression;
- statistics и другую metadata.

Колоночная организация помогает projection и filtering, но маленький Parquet может быть
больше CSV из-за metadata. Формат выбирают по схеме и workload, а не по одному размеру.

## Соберите это

До чтения CSV объявите:

```python
schema = pa.schema([
    pa.field("order_id", pa.string(), nullable=False),
    pa.field("amount", pa.decimal128(12, 2), nullable=False),
    pa.field("ordered_at", pa.timestamp("us", tz="UTC"), nullable=False),
])
```

Преобразуйте строки в Decimal и timezone-aware datetime. Затем создайте Arrow Table именно
с этой schema. Ошибка приведения должна назвать строку и поле.

```bash
uv run --locked python code/main.py
```

## Используйте это

PyArrow записывает типизированную таблицу:

```python
pq.write_table(
    table,
    "orders.parquet",
    compression="zstd",
    write_statistics=True,
)
```

После записи прочитайте файл обратно и сравните schema, row count и null counts.

```bash
uv run --locked python outputs/parquet_converter.py \
  --input ../data/tiny/orders_typed.csv \
  --output orders.parquet \
  --schema ../data/parquet_schema.json \
  --manifest manifest.json
```

## Сломайте это

1. Переименуйте `order_id` в CSV.
2. Запишите нечисловой amount.
3. Уберите timezone из timestamp.
4. Сделайте пустым non-null user_id.
5. Измените scale decimal с 2 на 1.

Каждый дефект должен остановить публикацию финального Parquet.

## Проверьте это

- amount имеет `decimal128(12, 2)`;
- ordered_at имеет UTC timezone;
- сумма равна Decimal `3226.59`;
- два пустых comment становятся null;
- compression metadata равна ZSTD;
- source и output имеют SHA-256;
- DuckDB читает projection и filter;
- header drift отклоняется.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/parquet_converter.py` атомарно публикует Parquet и по запросу записывает manifest.
Артефакт подходит как граница между внешним текстовым источником и типизированным
аналитическим хранением.

## Упражнения

1. Сравните ZSTD, Snappy и отсутствие compression на sample-наборе.
2. Запишите несколько row groups и исследуйте metadata.
3. Добавьте enum/domain check валюты до конвертации.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Columnar format | Таблица, показанная колонками | Физическая организация значений по columns/chunks |
| Row group | Отдельная таблица | Горизонтальный блок строк с column chunks |
| Logical type | Python dtype | Семантика поверх физического представления |
| Compression | Замена schema | Сжатие encoded pages без изменения типов |
| Projection | SELECT всех полей | Чтение только требуемых колонок |

## Дополнительное чтение

- [PyArrow: Parquet](https://arrow.apache.org/docs/python/parquet.html) — изучите schema, compression, row groups и metadata.
- [Apache Parquet format](https://parquet.apache.org/docs/file-format/) — свяжите row groups, column chunks и pages.
- [pandas: `read_parquet`](https://pandas.pydata.org/docs/reference/api/pandas.read_parquet.html) — разберите columns, filters и dtype backend.
- [DuckDB: Parquet](https://duckdb.org/docs/stable/data/parquet/overview) — изучите direct query, projection и filter pushdown.
