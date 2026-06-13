# Учебные данные фазы 04

Фаза использует четыре связанные таблицы продуктового сервиса: `users`, `orders`,
`order_items` и `events`.

- `tiny/` хранится в Git и предназначен для ручного расчета, проверки SQL-семантики и
  behavioral tests.
- `sample/` генерируется локально и содержит более 500 тысяч строк для `EXPLAIN`,
  `EXPLAIN ANALYZE` и сравнения планов запросов.

Источник правды для grain, ключей, связей, колонок и известных дефектов находится в
`contract.json`. Каждый сгенерированный профиль получает `manifest.json` с количеством
строк и SHA-256 файлов.

Воспроизвести committed tiny-набор:

```bash
uv run --locked python phases/04-sql-and-duckdb/data/generate_data.py \
  --profile tiny
```

Создать локальный sample-набор:

```bash
uv run --locked python phases/04-sql-and-duckdb/data/generate_data.py \
  --profile sample
```

Каталог `sample/` исключен из Git. Генератор не требует pandas или DuckDB и строит данные
детерминированно средствами стандартной библиотеки Python.
