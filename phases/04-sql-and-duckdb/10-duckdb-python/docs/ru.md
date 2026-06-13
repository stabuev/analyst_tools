# DuckDB из Python

> Python оркестрирует запрос, но SQL, параметры, connection и результат должны иметь явный контракт.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 04/09
**Время:** ~90 минут
**Результат:** выполняет параметризованный SQL и передает результат в pandas без globals.

## Цели обучения

- Управлять жизненным циклом `DuckDBPyConnection`.
- Передавать значения параметрами DB API.
- Проверять колонки и dtypes DataFrame-результата.
- Выбирать границу: агрегировать в SQL, анализировать компактный результат в pandas.

## Проблема

Ноутбук использует `duckdb.sql()` и DataFrame из глобального namespace. Функция работает
только при определенном порядке ячеек, connection невозможно подменить в тесте, а путь и
порог собираются f-string. Такой код нельзя безопасно превратить в pipeline.

## Концепция

Интерфейс runner:

```text
SQL text + params + optional connection + expected columns
-> pandas DataFrame + metadata
```

Если connection создал runner, он ее закрывает. Если connection передал вызывающий код,
он же управляет lifecycle.

## Соберите это

Минимальная версия:

```python
connection = duckdb.connect()
try:
    frame = connection.execute(sql, params).fetchdf()
finally:
    connection.close()
```

Добавьте проверку колонок и только затем возвращайте DataFrame.

```bash
uv run --locked python code/main.py
```

## Используйте это

`outputs/paid_orders.sql` хранит SQL отдельно от Python. Путь к CSV и порог передаются как
два `?`. Runner не знает предметную область запроса, но проверяет read-only режим и схему.

```python
frame, metadata = execute_query(
    sql,
    [orders_path, 500],
    expected_columns=["order_id", "user_id", "currency", "amount"],
)
```

## Сломайте это

1. Создайте глобальную connection и запустите тесты в другом порядке.
2. Закройте connection, переданную вызывающим кодом.
3. Подставьте путь через f-string.
4. Измените alias в SQL и не обновите downstream pandas.
5. Передайте миллион сырых строк вместо агрегированного результата.

## Проверьте это

Тесты подтверждают параметры, ownership connection, read-only guard, expected columns и
CLI. Порог 500 дает пять строк, порог 1000 — две.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/duckdb_runner.py \
  --sql-file outputs/paid_orders.sql \
  --params-json '["../data/tiny/orders.csv", 500]' \
  --expected-columns order_id,user_id,currency,amount
```

Runner можно использовать для небольших проверяемых SQL assets без скрытого состояния.

## Упражнения

1. Добавьте запись результата в Parquet.
2. Передайте тестовую in-memory connection с временной таблицей.
3. Добавьте контракт максимального числа строк.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Connection ownership | Кто вызвал execute | Кто создает, закрывает и управляет ресурсом |
| Parameter binding | Форматирование строки | Передача значения отдельно от SQL syntax |
| fetchdf | Выполнение в pandas | Передача уже вычисленного результата в DataFrame |
| Boundary | Импорт библиотеки | Место смены движка и контракта данных |
| Global state | Удобная переменная | Скрытая зависимость от процесса и порядка выполнения |

## Дополнительное чтение

- [DuckDB: Python DB API](https://duckdb.org/docs/current/clients/python/dbapi) — изучите connections, execute, parameters и fetch methods.
- [DuckDB: Export to Pandas](https://duckdb.org/docs/current/guides/python/export_pandas) — сравните `fetchdf`, `df` и batch-oriented варианты.
- [DuckDB: SQL on Pandas](https://duckdb.org/docs/current/guides/python/sql_on_pandas) — разберите replacement scans и границы скрытого namespace.
- [PEP 249](https://peps.python.org/pep-0249/) — прочитайте общий контракт Python DB API, транзакций и курсоров.
