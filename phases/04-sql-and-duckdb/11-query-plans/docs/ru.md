# Планы запросов и стоимость

> Оптимизация начинается с эквивалентного результата и наблюдаемого плана, а не с догадки.

**Тип:** Learn
**Треки:** Core
**Пререквизиты:** 04/10
**Время:** ~90 минут
**Результат:** читает EXPLAIN ANALYZE и находит лишние scans.

## Цели обучения

- Различать logical result, physical operators и фактические метрики.
- Читать scan, filter, aggregate и join в плане.
- Находить повторное чтение одного источника.
- Сравнивать только семантически эквивалентные запросы.
- Не делать вывод о скорости по одному tiny-run.

## Проблема

Отчету нужны число `order_paid` событий и distinct active users. Два scalar-subquery
читают один CSV независимо. На tiny это почти незаметно, но на 200 тысячах событий лишний
scan становится реальной стоимостью.

## Концепция

`EXPLAIN` показывает выбранный план, не выполняя запрос. `EXPLAIN ANALYZE` выполняет его и
добавляет фактические rows и время операторов.

Оптимизационный контракт:

```text
result_before = result_after
scan_nodes_after < scan_nodes_before
timing is measured repeatedly on representative data
```

## Соберите это

Первый вариант содержит две независимые агрегации над одним CSV. Второй использует один
scan и два агрегата с `FILTER`.

```sql
SELECT
    count(*) FILTER (WHERE event_name = ?) AS event_rows,
    count(DISTINCT user_id) FILTER (WHERE event_name = ?) AS active_users
FROM read_csv(?);
```

```bash
uv run --locked python code/main.py
```

## Используйте это

Сгенерируйте representative sample:

```bash
uv run --locked python ../data/generate_data.py --profile sample
```

Затем запустите:

```bash
uv run --locked python outputs/plan_report.py \
  --events ../data/sample/events.csv
```

Отчет сохраняет полный plan text, число `TABLE_SCAN`, parsed total time и результат.

## Сломайте это

1. Сравните запросы с разной семантикой фильтра.
2. Объявите победителя по одному запуску tiny.
3. Смотрите только на общий runtime и игнорируйте rows операторов.
4. Добавьте лишний CTE, который повторно читает источник.

## Проверьте это

На tiny оба запроса возвращают шесть доставленных `order_paid` строк и трех активных
пользователей. Первый plan содержит два scan nodes, второй один.

Тесты намеренно не требуют, чтобы optimized query был быстрее на tiny: это было бы
нестабильным benchmark assertion.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/plan_report.py` — CLI сравнения plan shape и результата. Для выводов о времени
повторяйте запуски на `sample/`, фиксируйте окружение и используйте медиану.

## Упражнения

1. Добавьте warm-up и пять повторов вне `EXPLAIN ANALYZE`.
2. Сравните projection всех колонок и только нужных.
3. Найдите plan с JOIN и объясните build/probe стороны.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Logical plan | Текст SQL | Реляционные операции после анализа запроса |
| Physical plan | Результат | Конкретные операторы выполнения |
| Scan | Просто FROM | Чтение физического источника |
| Cardinality estimate | Точное число строк | Оценка оптимизатора до выполнения |
| EXPLAIN ANALYZE | Безопасный preview | Реальное выполнение с профилированием |

## Дополнительное чтение

- [DuckDB: EXPLAIN](https://duckdb.org/docs/current/guides/meta/explain) — разберите physical plan и оценки cardinality.
- [DuckDB: EXPLAIN ANALYZE](https://duckdb.org/docs/current/guides/meta/explain_analyze) — изучите фактические rows и время операторов.
- [DuckDB: Profiling](https://duckdb.org/docs/current/dev/profiling) — углубитесь в profiler metrics и форматы вывода.
- [DuckDB Performance Guide](https://duckdb.org/docs/current/guides/performance/overview) — прочитайте рекомендации по данным, схеме и workload.
