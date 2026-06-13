# Joins без размножения метрик

> JOIN корректен только тогда, когда его cardinality совместима с grain метрики.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 04/04
**Время:** ~105 минут
**Результат:** предсказывает cardinality JOIN, обнаруживает fanout и сохраняет метрики.

## Цели обучения

- Предсказывать `one-to-one`, `one-to-many` и `many-to-many`.
- Видеть, как fanout размножает метрики родительского grain.
- Предварительно агрегировать дочернюю таблицу до нужного ключа.
- Проверять unmatched-ключи и сохранение строк.

## Проблема

`orders.amount` имеет grain заказа, а `order_items` — товарной позиции. Наивный JOIN дает
14 строк вместо 12. Заказы `O1001` и `O1005` имеют по две позиции, поэтому их суммы
попадают в `SUM` дважды. Ошибочный результат `7705` выглядит правдоподобно, хотя верная
оплаченная выручка равна `5005`.

## Концепция

Перед JOIN запишите:

| Левая таблица | Правая таблица | Связь | Grain результата |
|---|---|---|---|
| orders | order_items | one-to-many | одна позиция заказа |
| orders | item_totals | one-to-one | один заказ |
| orders | users | many-to-one | один заказ |

Метрику можно суммировать после JOIN только если она аддитивна на новом grain или была
преобразована до него осознанно.

## Соберите это

Ручной пример:

```text
O1001 amount=1200, items=[P01, P02]
```

После JOIN:

```text
O1001 P01 1200
O1001 P02 1200
```

`SUM(amount)` дает `2400`. Правильный прием: сначала получить одну строку `item_totals` на
`order_id`, затем соединить ее с `orders`.

```bash
uv run --locked python code/main.py
```

## Используйте это

```sql
WITH item_totals AS (
    SELECT
        order_id,
        count(*) AS item_rows,
        sum(quantity * unit_price) AS item_total
    FROM order_items
    GROUP BY order_id
)
SELECT orders.*, item_totals.item_rows, item_totals.item_total
FROM orders
LEFT JOIN item_totals USING (order_id);
```

`LEFT JOIN users` сохраняет `U999` как диагностическую строку с отсутствующим родителем.
`INNER JOIN` скрыл бы проблему и уменьшил число заказов.

## Сломайте это

1. Сложите `orders.amount` после прямого JOIN к позициям.
2. Добавьте дубликат `users.user_id` и повторите many-to-one JOIN.
3. Замените `LEFT JOIN users` на `INNER JOIN`.
4. Используйте `DISTINCT amount` как попытку починить fanout.

`DISTINCT amount` не является исправлением: два разных заказа могут иметь одинаковую
сумму.

## Проверьте это

Контрольные значения:

- 12 заказов;
- 14 строк прямого JOIN к позициям;
- наивная выручка `7705`;
- безопасная выручка `5005`;
- fanout `2700`;
- один заказ с неизвестным пользователем;
- две многопозиционные покупки.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/safe_join.py \
  --users ../data/tiny/users.csv \
  --orders ../data/tiny/orders.csv \
  --items ../data/tiny/order_items.csv
```

CLI сравнивает наивный и безопасный варианты и поставляет cardinality-checks.

## Упражнения

1. Добавьте дубликат пользователя и обнаружьте many-to-many.
2. Посчитайте число unmatched-позиций через anti join.
3. Добавьте контроль суммы `item_total` и `orders.amount`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cardinality | Число строк таблицы | Число соответствий ключей между сторонами JOIN |
| Fanout | Любое увеличение строк | Размножение строки из-за нескольких соответствий |
| Unmatched key | Строка для удаления | Ключ без пары, требующий явной политики |
| Pre-aggregation | Оптимизация | Возврат дочерних данных к требуемому grain |
| Semi/anti join | Вариант INNER JOIN | Проверка существования или отсутствия без размножения |

## Дополнительное чтение

- [DuckDB: FROM and JOIN](https://duckdb.org/docs/current/sql/query_syntax/from) — разберите outer, semi, anti и positional joins.
- [DuckDB: Join Operations](https://duckdb.org/docs/current/guides/performance/join_operations) — изучите физическую сторону соединений и порядок таблиц.
- [DuckDB: GROUP BY](https://duckdb.org/docs/current/sql/query_syntax/groupby) — повторите предварительную агрегацию до ключа соединения.
- [PostgreSQL: Joined Tables](https://www.postgresql.org/docs/current/queries-table-expressions.html#QUERIES-JOIN) — сопоставьте стандартные типы JOIN и условия соединения.
