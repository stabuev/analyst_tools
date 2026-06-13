# Arrow как контракт обмена таблицами

> Arrow полезен не обещанием zero-copy, а возможностью проверить типизированный обмен без CSV.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 05/08  
**Время:** ~60 минут  
**Результат:** передает таблицу между pandas, Arrow и DuckDB и проверяет схему, пропуски и
факт копирования данных.

## Цели обучения

- Отличать Arrow memory model от Parquet file format.
- Сохранять Arrow-backed dtypes в pandas.
- Передавать Arrow Table в DuckDB и получать Arrow result.
- Измерять buffer reuse вместо предположения о zero-copy.

## Проблема

Один pipeline записывает промежуточный CSV между pandas и DuckDB. Тип decimal становится
float, timezone требует повторного парсинга, а null policy задается заново. Переход на
Arrow называют zero-copy, но не проверяют, произошло ли копирование.

## Концепция

Arrow schema описывает fields, types и nullable для in-memory arrays. Parquet использует
похожие типы, но является форматом хранения.

Обмен нужно проверять по четырем измерениям:

1. schema;
2. values;
3. null counts;
4. memory buffers.

Zero-copy возможен только при совместимом layout. Конвертация object strings или смена
типа требует новой памяти. pandas также не переносит field-level `nullable=False` обратно
в Arrow schema автоматически: типы и фактические null counts нужно проверять отдельно от
этого ограничения metadata.

## Соберите это

Создайте pandas columns с Arrow-backed dtypes и превратите DataFrame в Table:

```python
table = pa.Table.from_pandas(frame, preserve_index=False)
returned = table.to_pandas(types_mapper=pd.ArrowDtype)
```

Для проверки памяти получите `buffer.address` у chunks до и после roundtrip. Совпадение
адресов является наблюдаемым фактом reuse; несовпадение не означает ошибку данных.

```bash
uv run --locked python code/main.py
```

## Используйте это

DuckDB принимает Arrow Table напрямую:

```python
connection.register("orders_arrow", table)
result = connection.execute("SELECT ... FROM orders_arrow").arrow().read_all()
```

Артефакт читает Parquet, проходит Arrow -> pandas -> Arrow и Arrow -> DuckDB -> Arrow:

```bash
uv run --locked python outputs/arrow_compatibility.py \
  --input orders.parquet \
  --output compatibility.json
```

## Сломайте это

1. Превратите Arrow-backed string в Python object.
2. Сбросьте timezone timestamp.
3. Замените Decimal на float.
4. Заполните null пустой строкой.
5. Добавьте pandas index в Arrow metadata.

Отчет должен отделять несовместимость данных от допустимого копирования.

## Проверьте это

- пять rows сохраняются во всех системах;
- decimal и UTC timestamp переживают pandas roundtrip;
- два null comment не меняются;
- потеря field-level nullability показана отдельно, а не скрыта;
- pandas dtypes остаются Arrow-backed;
- buffer reuse измеряется по каждому столбцу;
- DuckDB считает сумму `3226.59`;
- DuckDB возвращает Arrow schema.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/arrow_compatibility.py` выпускает JSON-отчет совместимости. Его можно запускать
после обновления pandas, PyArrow или DuckDB, чтобы проверить реальный exchange contract.

## Упражнения

1. Сравните обычные pandas dtypes и Arrow-backed dtypes.
2. Добавьте dictionary-encoded category.
3. Проверьте large string и timestamp другой точности.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Arrow | Сжатый файл | In-memory format и набор interfaces для типизированного обмена |
| Buffer | Python list | Непрерывная область памяти array |
| Zero-copy | Любой быстрый переход | Повторное использование существующих buffers |
| ArrowDtype | Обычный object | pandas dtype с Arrow-backed storage |
| Interchange contract | Совпадающий row count | Сохранение schema, values, nulls и понятного memory behavior |

## Дополнительное чтение

- [PyArrow: pandas integration](https://arrow.apache.org/docs/python/pandas.html) — изучите conversion rules, nullable types и zero-copy conditions.
- [Arrow columnar format](https://arrow.apache.org/docs/format/Columnar.html) — разберите validity bitmap, buffers и nested layout.
- [DuckDB: Python API](https://duckdb.org/docs/stable/clients/python/overview) — изучите регистрацию Arrow objects и возврат результата.
- [DataFrame interchange protocol](https://data-apis.org/dataframe-protocol/latest/index.html) — сравните общий protocol обмена с прямой Arrow integration.
