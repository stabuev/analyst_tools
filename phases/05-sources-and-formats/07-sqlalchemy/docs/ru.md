# Подключение к БД через SQLAlchemy

> SQL-структура и пользовательские значения должны встречаться только внутри driver, а не в строковой интерполяции.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 05/06  
**Время:** ~90 минут  
**Результат:** читает параметризованный срез через SQLAlchemy Core, управляет соединением
и не интерполирует значения в SQL.

## Цели обучения

- Разделять Engine, Connection, statement и parameters.
- Строить SELECT через SQLAlchemy Core.
- Передавать значения bind parameters.
- Проверять схему и grain результата.

## Проблема

Скрипт формирует `WHERE status = '{status}'`. Значение
`paid' OR 1=1 --` превращает фильтр в другой SQL. Одновременно соединение создается
глобально и не закрывается после ошибки.

## Концепция

SQLAlchemy Core разделяет:

| Объект | Ответственность |
|---|---|
| Engine | конфигурация DBAPI и pool |
| Connection | ограниченный ресурс выполнения |
| Table/Column | SQL identifiers |
| Statement | структура запроса |
| Parameters | значения, связанные driver |

Bind parameters защищают значения. Динамические имена таблиц и столбцов являются
структурой SQL и должны приходить из allowlist или объектов metadata.

## Соберите это

На уровне DB-API безопасный запрос использует placeholder:

```python
connection.execute(
    "SELECT order_id FROM orders WHERE amount >= ?",
    (900,),
)
```

SQLAlchemy строит ту же границу:

```python
statement = select(orders).where(
    orders.c.amount >= bindparam("min_amount")
)
connection.execute(statement, {"min_amount": 900})
```

```bash
uv run --locked python code/main.py
```

## Используйте это

Артефакт отражает таблицы из metadata, строит JOIN orders/users, применяет status,
min_amount и limit как параметры и выполняет запрос внутри:

```python
with engine.connect() as connection:
    rows = connection.execute(statement, params).mappings().all()
```

```bash
uv run --locked python outputs/db_reader.py \
  --database ../data/tiny/analytics.sqlite \
  --status paid \
  --min-amount 900
```

Engine освобождается через `dispose`, а результат проверяется по JSON-контракту.

## Сломайте это

Передайте `paid' OR 1=1 --` как status. Корректный клиент вернет ноль строк и не изменит
таблицу. Попробуйте также:

1. отрицательный limit;
2. отсутствующую базу;
3. неизвестный status в source;
4. удаленный столбец result contract;
5. interpolated table name без allowlist.

## Проверьте это

- `paid` и min amount 900 дают три заказа;
- SQL не содержит literal `'paid'`;
- bind names включают status и limit;
- injection string является обычным значением;
- таблица после запроса содержит пять строк;
- result columns и grain соответствуют контракту;
- limit соблюдается.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/db_reader.py` является параметризованным read-only reader. JSON-отчет содержит
compiled SQL без literal values, список bind names, database schema и проверенный result.

## Упражнения

1. Добавьте диапазон дат двумя bind parameters.
2. Реализуйте allowlist сортировки.
3. Подключите другую SQLAlchemy-compatible БД через URL из environment.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Engine | Открытое соединение | Factory и pool подключения к DBAPI |
| Connection | Глобальный singleton | Ограниченный ресурс выполнения SQL |
| Bind parameter | Экранированная f-string | Значение, переданное driver отдельно от SQL |
| Reflection | Копирование данных | Чтение metadata существующей схемы |
| SQLAlchemy Core | ORM | Expression language для SQL без объектной модели домена |

## Дополнительное чтение

- [SQLAlchemy: Engines and Connections](https://docs.sqlalchemy.org/en/20/core/connections.html) — изучите lifecycle Engine, Connection и transaction.
- [SQLAlchemy: SELECT](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html) — разберите Core statements, joins и bind parameters.
- [SQLAlchemy: Working with Transactions](https://docs.sqlalchemy.org/en/20/tutorial/dbapi_transactions.html) — сопоставьте context managers, commit и rollback.
- [OWASP: SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html) — сравните parameterized queries и опасную string concatenation.
