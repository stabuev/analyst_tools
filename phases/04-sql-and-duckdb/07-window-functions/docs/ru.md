# Оконные функции

> Окно сохраняет grain строки, но его смысл полностью задают partition, order и frame.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 04/06
**Время:** ~90 минут
**Результат:** выбирает окно и проверяет ранги, лаги и накопительные метрики.

## Цели обучения

- Отличать оконный расчет от GROUP BY.
- Выбирать `PARTITION BY` и детерминированный `ORDER BY`.
- Использовать `row_number`, `rank`, `lag` и накопительную `sum`.
- Объяснять разницу `ROWS` и `RANGE`.

## Проблема

Нужно пронумеровать покупки пользователя, получить предыдущую сумму и накопительную
выручку. GROUP BY уничтожит строки заказов, а окно сохранит одну строку на `order_id`.
Однако порядок только по дате может иметь ties, а неявный frame способен включить сразу
несколько peer-строк.

## Концепция

Оконный контракт содержит три части:

```sql
OVER (
    PARTITION BY user_id
    ORDER BY ordered_at, order_id
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
```

- partition определяет независимую последовательность;
- order задает положение строки;
- frame задает множество строк для агрегата относительно текущей.

## Соберите это

Для U001:

| order_id | amount | number | previous | cumulative |
|---|---:|---:|---:|---:|
| O1001 | 1200 | 1 | NULL | 1200 |
| O1005 | 1500 | 2 | 1200 | 2700 |

Этот ручной результат является oracle.

```bash
uv run --locked python code/main.py
```

## Используйте это

```sql
row_number() OVER user_order AS order_number,
lag(amount) OVER user_order AS previous_amount,
sum(amount) OVER (
    PARTITION BY user_id
    ORDER BY ordered_at, order_id
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS cumulative_amount
```

Именованное окно сокращает повторение partition/order, но frame накопительной суммы
оставлен явным рядом с агрегатом.

## Сломайте это

Встроенный demo содержит ключи порядка `[1, 1, 2]`. Для первой строки:

- `ROWS` дает 10;
- `RANGE` сразу включает обе строки с ключом 1 и дает 30.

Уберите `order_id` из порядка, добавьте две покупки в одну секунду и наблюдайте
недетерминированность `row_number`.

## Проверьте это

- 9 оплаченных заказов остаются 9 строками;
- `order_id` уникален;
- U001 имеет cumulative `1200, 2700`;
- U007 заканчивает cumulative `1600`;
- frame demo явно различает `ROWS` и `RANGE`.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/window_metrics.py \
  --orders ../data/tiny/orders.csv
```

Артефакт поставляет набор оконных метрик и отдельный frame experiment.

## Упражнения

1. Добавьте `lead` для следующей суммы.
2. Рассчитайте разницу между текущим и предыдущим заказом.
3. Получите последний заказ пользователя через `QUALIFY`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Window | То же, что GROUP BY | Контекст расчета без сворачивания строк |
| Partition | Физический файл | Независимая группа строк окна |
| Peer | Дубликат строки | Строка с равными ключами ORDER BY |
| Frame | Вся partition всегда | Подмножество partition относительно текущей строки |
| Tie-breaker | Косметическая сортировка | Дополнительный ключ детерминированного порядка |

## Дополнительное чтение

- [DuckDB: Window Functions](https://duckdb.org/docs/current/sql/functions/window_functions) — изучите функции, partition, order и frames.
- [DuckDB: WINDOW Clause](https://duckdb.org/docs/current/sql/query_syntax/window) — разберите переиспользование именованных окон.
- [DuckDB: QUALIFY](https://duckdb.org/docs/current/sql/query_syntax/qualify) — фильтруйте результат окна без дополнительного CTE.
- [PostgreSQL: Window Functions](https://www.postgresql.org/docs/current/tutorial-window.html) — сравните стандартную модель partition и frame.
