# DuckDB и данные больше памяти

> Out-of-core execution - это проверяемая конфигурация и план запроса, а не гарантия,
> что любой большой SQL переживет маленький `memory_limit`.

**Тип:** Case
**Треки:** Data, ML
**Пререквизиты:** `12-performance/05-arrow-memory`
**Время:** ~90 минут
**Результат:** запускает DuckDB workload с заданными memory_limit, temp_directory и
threads, читает EXPLAIN/EXPLAIN ANALYZE, распознает blocking operators и проверяет
larger-than-memory ограничения.

## Цели обучения

- Настроить DuckDB через `memory_limit`, `temp_directory`, `max_temp_directory_size` и
  `threads`.
- Прочитать `EXPLAIN` как physical plan, а не как декоративный лог.
- Отличить streaming-friendly scan от blocking operators: join, aggregate, window,
  order.
- Использовать `EXPLAIN ANALYZE` как runtime evidence и не путать его с benchmark.
- Оформить runbook, который честно говорит, был ли spill на диск, и где остаются OOM
  риски.

## Проблема

Команда считает недельную витрину `customer_revenue_health_weekly`. После уроков про
Parquet и Arrow pipeline уже читает только нужные колонки и умеет объяснить memory
layout. Но объем данных растет: локальный pandas-процесс больше не помещается в память,
а полный перенос в warehouse пока не нужен.

DuckDB кажется идеальным решением:

```text
Поставим маленький memory_limit, temp_directory - и все большие запросы начнут spill на диск.
```

Это опасное упрощение. DuckDB действительно умеет out-of-core execution и может
использовать временную директорию, но не каждый оператор одинаково легко spill-ится.
Сортировка, hash aggregation, window functions и hash join держат промежуточное
состояние. Несколько таких операторов в одном запросе могут создать пик памяти даже при
правильной temp directory.

В этом уроке мы не устраиваем искусственный OOM. Вместо этого собираем воспроизводимый
runbook: фиксируем настройки, строим запрос с несколькими blocking operators, читаем
план и профиль, сверяем результат с pandas-контролем и явно пишем, был ли spill
наблюдаемым фактом.

## Концепция

DuckDB - локальный аналитический SQL engine. Для performance-задачи важны четыре слоя.

### Memory budget

`memory_limit` ограничивает память, которой управляет buffer manager DuckDB. Это не
абсолютный лимит RSS всего Python-процесса: результаты запроса, векторы, некоторые
aggregate states и память расширений могут жить вне этой границы. Поэтому хороший отчет
пишет:

```text
memory_limit = задан
actual process memory = отдельная метрика, если мы ее измеряли
OOM risk = не исчезает
```

### Temporary directory

`temp_directory` говорит DuckDB, куда писать временные данные, если оператор может
перейти на диск. Для production-подобного запуска нужно также ограничить
`max_temp_directory_size`: иначе spill может неожиданно занять весь доступный диск.

### Threads

`threads` влияет на параллельное выполнение. Больше потоков не всегда лучше: они могут
ускорить scan, но увеличить одновременное потребление памяти. В учебном артефакте
используется `threads=1`, чтобы отчет был стабильнее и проще читался.

### Blocking operators

Streaming-friendly operator может отдавать строки дальше по мере чтения input. Blocking
operator должен собрать состояние:

| Operator | Почему это риск larger-than-memory |
|---|---|
| `HASH_JOIN` | build-side таблица хранится в памяти или spill-ится по правилам engine |
| `HASH_GROUP_BY` | группы и aggregate state живут до завершения input |
| `WINDOW` | partition/order state нужен до вычисления окна |
| `ORDER_BY` | полный порядок требует координации всех строк результата |

Если план содержит несколько blocking operators, `temp_directory` помогает, но не
является доказательством безопасности.

## Соберите это

Артефакт урока создает маленький Parquet-workload с тем же смыслом, что и будущий
большой pipeline. Размер намеренно безопасный для CI и ноутбука студента.

### Шаг 1. Сгенерируйте источники

```python
orders, users = generate_customer_revenue_workload(
    rows=12_000,
    users=800,
    seed=42,
)
```

`orders` содержит `week_start`, `platform`, `paid_orders`, `net_revenue_cents` и широкую
`payload`-колонку. `users` содержит `segment`, `region`, `plan` и канал привлечения.
Это не production extract, но grain и keys совпадают с задачей:

```text
orders grain: один заказ
users grain: один пользователь
join key: user_id
output grain: week_start, segment, platform
```

### Шаг 2. Запишите Parquet

```python
paths = write_workload_files(orders, users, "/tmp/duckdb-out-of-core")
```

В директории появятся:

```text
data/orders.parquet
data/users.parquet
```

Parquet нужен не ради формата как такового. Он дает DuckDB columnar scan и продолжает
линию предыдущих уроков: сначала уменьшаем лишнее чтение, затем выбираем engine.

### Шаг 3. Зафиксируйте настройки DuckDB

```python
connection = duckdb.connect(":memory:")
settings = configure_connection(
    connection,
    temp_directory="/tmp/duckdb-out-of-core/duckdb-temp",
    memory_limit="64MB",
    threads=1,
    max_temp_directory_size="256MB",
)
```

Отчет сохраняет не только запрошенные значения, но и значения, которые вернул DuckDB
через `current_setting`. Например, `64MB` может быть отображено как `61.0 MiB`: это
нормализация единиц, а не ошибка.

### Шаг 4. Постройте SQL с blocking operators

Запрос считает недельную выручку по сегменту и платформе, затем ранжирует сегменты
внутри недели:

```sql
WITH weekly AS (
  SELECT
    o.week_start,
    u.segment,
    o.platform,
    CAST(sum(o.net_revenue_cents) AS BIGINT) AS net_revenue_cents,
    CAST(sum(o.paid_orders) AS BIGINT) AS paid_orders,
    CAST(count(*) AS BIGINT) AS order_rows
  FROM read_parquet('data/orders.parquet') AS o
  INNER JOIN read_parquet('data/users.parquet') AS u
    USING (user_id)
  WHERE o.week_index BETWEEN 1 AND 6
  GROUP BY 1, 2, 3
),
ranked AS (
  SELECT
    *,
    CAST(rank() OVER (
      PARTITION BY week_start
      ORDER BY net_revenue_cents DESC
    ) AS BIGINT) AS revenue_rank
  FROM weekly
)
SELECT *
FROM ranked
WHERE revenue_rank <= 3
ORDER BY week_start, revenue_rank, segment, platform;
```

В нем есть scan, join, aggregate, window и final ordering. Это хороший учебный случай:
результат маленький, но план показывает memory-sensitive форму запроса.

### Шаг 5. Разберите plan

```python
plan = explain_query(connection, query)
operators = detect_plan_operators(plan)
blocking = classify_blocking_operators(plan)
```

Ожидаемые признаки:

```text
PARQUET_SCAN = true
HASH_JOIN = true
HASH_GROUP_BY = true
WINDOW = true
ORDER_BY = true
```

Если `EXPLAIN` не показывает нужный operator, нельзя делать вывод про его стоимость.
Сначала измените запрос или вход так, чтобы план действительно соответствовал сценарию.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/06-duckdb-out-of-core/code/main.py
```

Запустите CLI-артефакт и сохраните package:

```bash
uv run --locked python phases/12-performance/06-duckdb-out-of-core/outputs/duckdb_out_of_core_report.py \
  --rows 12000 \
  --users 800 \
  --seed 42 \
  --memory-limit 64MB \
  --threads 1 \
  --max-temp-directory-size 256MB \
  --output-dir /tmp/duckdb-out-of-core-report
```

В директории появятся:

- `data/orders.parquet` и `data/users.parquet` - воспроизводимые источники;
- `report.json` - machine-readable отчет;
- `query-plan.txt` - результат `EXPLAIN`;
- `query-profile.txt` - результат `EXPLAIN ANALYZE`;
- `runbook.md` - человекочитаемая инструкция и ограничения.

Минимально хороший отчет:

```text
interpretation.spill_ready = true
profile.has_runtime_evidence = true
equivalence.matches_control = true
interpretation.safe_to_ship = true
```

`spill_observed` может быть `false`. Для маленького учебного input это нормальный
результат. Важно, что отчет не превращает `spill_ready` в ложное утверждение "spill
точно произошел".

## Сломайте это

### Уберите temp_directory

Если временная директория не задана явно, отчет перестает быть переносимым. На одной
машине spill может попасть в удобное место, на другой - в маленький системный раздел.

### Поднимите threads без памяти

Поставьте `--threads 8` и оставьте маленький `memory_limit`. На реальных данных это
может ускорить scan, но увеличить одновременное memory pressure. Threads должны быть
частью сценария, а не скрытой настройкой ноутбука.

### Добавьте еще одну полную сортировку

`ORDER BY` после window уже является blocking operator. Если добавить сортировку внутри
нескольких CTE, план может стать красивым SQL и плохим larger-than-memory кандидатом.

### Поверьте только успешному запуску

Если запрос прошел на 12 000 строк, это не доказывает, что он пройдет на 120 миллионах.
Успешный small run доказывает корректность контракта и форму плана, но не заменяет
benchmark и load test.

### Игнорируйте контрольный результат

Performance-решение без equivalence gate бесполезно. В уроке DuckDB-результат сверяется
с pandas-контролем по `week_start`, `segment`, `platform`, суммам и rank.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/06-duckdb-out-of-core/tests
```

Проверка артефакта:

```bash
uv run --locked python phases/12-performance/06-duckdb-out-of-core/outputs/duckdb_out_of_core_report.py \
  --rows 2400 \
  --users 240 \
  --output-dir /tmp/duckdb-out-of-core-smoke
```

Контракт отчета:

- настройки DuckDB прочитаны обратно через `current_setting`;
- `temp_directory` существует;
- план содержит Parquet scan и несколько blocking operators;
- `EXPLAIN ANALYZE` содержит runtime evidence;
- DuckDB-результат совпадает с pandas-контролем;
- `spill_ready` и `spill_observed` разделены;
- ограничения larger-than-memory явно перечислены в `runbook.md`.

## Поставьте результат

Именованный артефакт урока - CLI `duckdb-out-of-core-report`:

```bash
uv run --locked python phases/12-performance/06-duckdb-out-of-core/outputs/duckdb_out_of_core_report.py \
  --rows 12000 \
  --users 800 \
  --memory-limit 64MB \
  --threads 1 \
  --output-dir /tmp/duckdb-out-of-core-report
```

Его можно использовать вне урока как шаблон для локального larger-than-memory smoke
test:

1. замените генератор данных на реальные Parquet paths;
2. оставьте блок настройки DuckDB явным;
3. сохраните `EXPLAIN`, `EXPLAIN ANALYZE` и temp-directory observation;
4. добавьте control/equivalence check для бизнес-результата;
5. не пишите "DuckDB умеет данные больше памяти" без списка blocking operators и
   условий, при которых вы это проверили.

## Упражнения

1. Запустите артефакт с `--threads 1` и `--threads 4`. Сравните plan и profile text:
   какие части отчета изменились, а какие остались контрактом?
2. Измените SQL так, чтобы ранжирование считалось по `segment, platform` вместе.
   Обновите pandas-контроль и проверьте, что equivalence gate продолжает проходить.
3. Добавьте в runbook колонку `risk_level` для каждого blocking operator: low, medium
   или high. Обоснуйте правило классификации через rows, groups и memory budget.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| `memory_limit` | Абсолютный лимит памяти всего процесса | Лимит памяти, управляемой DuckDB buffer manager; часть allocations может быть вне него |
| `temp_directory` | Доказательство, что spill случился | Место, куда DuckDB может писать временные данные; факт spill нужно наблюдать отдельно |
| Out-of-core execution | Любой большой запрос автоматически безопасен | Engine может переносить часть работы на диск, но operator mix и temp budget остаются критичными |
| Blocking operator | Просто медленный operator | Operator, который должен удерживать промежуточное состояние до продолжения результата |
| `EXPLAIN ANALYZE` | Финальный benchmark | Выполненный профиль запроса с runtime evidence; для выбора движка нужны еще повторы и методология |

## Дополнительное чтение

- [DuckDB PRAGMA statements](https://duckdb.org/docs/current/configuration/pragmas) - прочитайте разделы `Memory Limit` и `Threads`, чтобы увидеть официальный синтаксис `SET memory_limit` и `SET threads`.
- [DuckDB configuration overview](https://duckdb.org/docs/current/configuration/overview) - используйте список settings как справочник для `temp_directory`, `max_temp_directory_size`, `current_setting` и `duckdb_settings()`.
- [DuckDB EXPLAIN ANALYZE](https://duckdb.org/docs/current/guides/meta/explain_analyze) - разберите, что профиль выполняет запрос и показывает runtime по операторам.
- [DuckDB tuning workloads](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads) - посмотрите разделы про blocking operators, threads, row groups и workloads, которые требуют больше памяти.
- [DuckDB out-of-memory troubleshooting](https://duckdb.org/docs/current/guides/troubleshooting/oom_errors) - прочитайте список причин, почему OOM возможен даже при наличии out-of-core engine.
