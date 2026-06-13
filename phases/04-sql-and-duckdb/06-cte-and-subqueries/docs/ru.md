# CTE и композиция запросов

> Именованный SQL-шаг полезен, когда у него есть собственный grain и проверяемый контракт.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 04/05
**Время:** ~75 минут
**Результат:** разбивает расчет на CTE и проверяет инварианты каждого шага.

## Цели обучения

- Разделять загрузку, типизацию, фильтрацию, агрегацию и JOIN.
- Давать CTE имена по смыслу преобразования.
- Проверять row count, ключ и метрики между шагами.
- Отличать читаемость CTE от обещания materialization.

## Проблема

Монолитный запрос одновременно читает CSV, приводит типы, фильтрует оплату, агрегирует
позиции и соединяет таблицы. Если итоговая выручка изменилась, неизвестно, на каком шаге:
при cast, фильтре или JOIN.

## Концепция

CTE — локально именованный реляционный результат. Хороший pipeline читается как граф:

```text
raw_orders -> typed_orders -> paid_orders -> final
raw_items  -> item_totals ----------------^
```

У каждого узла есть grain и инвариант. Например, типизация сохраняет 12 строк, фильтр
оставляет 9 оплаченных заказов, а финал сохраняет уникальность `order_id`.

## Соберите это

Сначала запишите шаги словами и ожидаемые counts:

```text
raw_orders: 12
typed_orders: 12
paid_orders: 9
item_totals: 12
final: 9
```

Только после этого соедините шаги в `WITH`.

```bash
uv run --locked python code/main.py
```

## Используйте это

```sql
WITH
typed_orders AS (...),
paid_orders AS (
    SELECT * FROM typed_orders WHERE status = 'paid'
),
item_totals AS (
    SELECT order_id, sum(quantity * unit_price) AS item_total
    FROM order_items
    GROUP BY order_id
),
final AS (
    SELECT paid_orders.*, item_totals.item_total
    FROM paid_orders
    LEFT JOIN item_totals USING (order_id)
)
SELECT * FROM final;
```

Артефакт дополняет pipeline scalar-subqueries, которые возвращают audit row со всеми
инвариантами.

## Сломайте это

1. Удалите одну позицию заказа и проверьте `missing_item_totals`.
2. Перенесите фильтр оплаты в финальный SELECT и сравните промежуточные counts.
3. Продублируйте заказ и проверьте `duplicate_final_keys`.
4. Используйте безымянные `cte1`, `cte2` и оцените читаемость ошибки.

## Проверьте это

Финальный этап имеет 9 уникальных заказов, выручку `5005`, полное покрытие позициями и
нулевое число расхождений между `amount` и `item_total`.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/cte_pipeline.py \
  --orders ../data/tiny/orders.csv \
  --items ../data/tiny/order_items.csv
```

CLI возвращает этапы, checks и общий `valid`.

## Упражнения

1. Добавьте CTE нормализации категорий.
2. Вынесите unmatched-заказы в отдельный диагностический шаг.
3. Сравните plan при `AS MATERIALIZED` и `AS NOT MATERIALIZED`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| CTE | Временная таблица на диске | Именованный результат в области statement |
| Composition | Склейка SQL-строк | Последовательность реляционных преобразований |
| Invariant | Ожидаемое число | Условие, которое обязано сохраняться |
| Materialization | Любой CTE | Физическое вычисление и хранение промежуточного результата |
| Inlining | Удаление CTE | Встраивание определения CTE оптимизатором |

## Дополнительное чтение

- [DuckDB: WITH](https://duckdb.org/docs/current/sql/query_syntax/with) — изучите обычные и рекурсивные CTE и правила materialization.
- [DuckDB: Subqueries](https://duckdb.org/docs/current/sql/expressions/subqueries) — сравните scalar, EXISTS и табличные подзапросы.
- [DuckDB: EXPLAIN](https://duckdb.org/docs/current/guides/meta/explain) — проверьте, как CTE представлен в физическом плане.
- [PostgreSQL: WITH Queries](https://www.postgresql.org/docs/current/queries-with.html) — сопоставьте композицию и recursive queries в зрелой SQL-системе.
