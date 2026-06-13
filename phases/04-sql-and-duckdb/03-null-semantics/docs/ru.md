# NULL и трехзначная логика

> NULL не равен пустой строке или нулю: он превращает условие в UNKNOWN.

**Тип:** Learn
**Треки:** Core
**Пререквизиты:** 04/02
**Время:** ~75 минут
**Результат:** предсказывает UNKNOWN и обрабатывает NULL без скрытой потери строк.

## Цели обучения

- Предсказывать `TRUE`, `FALSE` и `UNKNOWN` для `AND`, `OR` и `NOT`.
- Объяснять, почему `WHERE` отбрасывает неизвестный результат.
- Различать `COUNT(*)`, `COUNT(column)`, `IS NULL` и `COALESCE`.
- Делать политику пропусков явной частью расчета.

## Проблема

В `orders` два незавершенных заказа имеют `NULL amount`. Фильтр `amount > 100` возвращает
шесть строк, а его отрицание только четыре. Две строки не попали ни в одну группу. Если
аналитик мыслит только `истина/ложь`, потеря выглядит как ошибка движка.

## Концепция

SQL использует трехзначную логику. Сравнение с отсутствующим значением обычно дает
`UNKNOWN`.

| A | B | A AND B | A OR B |
|---|---|---|---|
| TRUE | UNKNOWN | UNKNOWN | TRUE |
| FALSE | UNKNOWN | FALSE | UNKNOWN |
| UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

`WHERE` сохраняет только `TRUE`. Поэтому `UNKNOWN` ведет себя как отфильтрованная строка,
но не становится `FALSE`. Проверки отсутствия записывают как `IS NULL` и `IS NOT NULL`.

## Соберите это

Разделите 12 заказов на три корзины для `amount > 100`:

```text
TRUE:    6
FALSE:   4
UNKNOWN: 2
```

Инвариант полного разбиения:

```text
true_rows + false_rows + unknown_rows = total_rows
```

Запустите ручной контроль и SQL:

```bash
uv run --locked python code/main.py
```

## Используйте это

Артефакт считает каждую корзину через `FILTER`:

```sql
count(*) FILTER (WHERE amount > 100) AS true_rows,
count(*) FILTER (WHERE NOT (amount > 100)) AS false_rows,
count(*) FILTER (WHERE (amount > 100) IS NULL) AS unknown_rows
```

Для подсчета строк используйте `COUNT(*)`. `COUNT(amount)` отвечает на другой вопрос:
сколько строк имеют непустой `amount`.

`COALESCE(amount, 0)` допустим только как бизнес-решение: он утверждает, что неизвестная
сумма эквивалентна нулю. Это не техническая очистка.

## Сломайте это

Сравните запросы:

```sql
WHERE amount <> 0
WHERE NOT amount = 0
WHERE amount IS DISTINCT FROM 0
```

Первые два исключат `NULL`; третий считает `NULL` отличным от нуля. Затем попробуйте
`NOT IN` со списком, содержащим `NULL`, и объясните неожиданный `UNKNOWN`.

## Проверьте это

Tiny-набор должен дать:

- 12 строк всего;
- 10 непустых `amount`;
- 6 `TRUE`, 4 `FALSE`, 2 `UNKNOWN`;
- полное разбиение на три корзины.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/null_semantics.py \
  --orders ../data/tiny/orders.csv \
  --threshold 100
```

CLI возвращает таблицу истинности и аудит фильтра. Его удобно использовать перед
изменением правил обработки пропусков.

## Упражнения

1. Добавьте отдельную категорию `missing` через `CASE`.
2. Сравните `NOT IN` и `NOT EXISTS` на наборе с `NULL`.
3. Проверьте, как `NULL` ведет себя в `GROUP BY`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| NULL | Пустая строка | Маркер отсутствующего или неизвестного значения |
| UNKNOWN | То же, что FALSE | Третий результат логического выражения |
| COALESCE | Автоматическая очистка | Явная замена первого NULL выбранным значением |
| COUNT(*) | Число непустых значений | Число строк |
| COUNT(expr) | Число строк | Число непустых результатов выражения |

## Дополнительное чтение

- [DuckDB: NULL Values](https://duckdb.org/docs/current/sql/data_types/nulls) — разберите сравнения, логические операции и `IN` с NULL.
- [DuckDB: Aggregate Functions](https://duckdb.org/docs/current/sql/functions/aggregates) — сравните поведение агрегатов на пустых группах и NULL.
- [DuckDB: Comparison Operators](https://duckdb.org/docs/current/sql/expressions/comparison_operators) — изучите `IS DISTINCT FROM` как NULL-safe сравнение.
- [PostgreSQL: Comparison Functions](https://www.postgresql.org/docs/current/functions-comparison.html) — сопоставьте стандартную SQL-семантику с DuckDB.
