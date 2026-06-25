# Lazy execution и оптимизация

> Lazy API полезен не тем, что "откладывает запуск", а тем, что дает optimizer увидеть
> весь расчет до чтения данных.

**Тип:** Case
**Треки:** Data, ML
**Пререквизиты:** `12-performance/07-polars-expressions`
**Время:** ~90 минут
**Результат:** строит lazy scan-план, читает optimized logical plan, подтверждает
projection/predicate pushdown и показывает, где ранний collect или UDF блокирует
оптимизацию.

## Цели обучения

- Построить lazy pipeline через `pl.scan_parquet`, а не eager `pl.read_parquet`.
- Сравнить unoptimized и optimized plan через `LazyFrame.explain`.
- Найти в optimized plan `PROJECT ... COLUMNS` и `SELECTION` у `Parquet SCAN`.
- Объяснить, почему ранний `collect()` и Python UDF ломают поле зрения optimizer.
- Проверить, что lazy-результат совпадает с pandas control.

## Проблема

В `12/07` мы уже перенесли pandas pipeline в Polars expressions. Но можно написать
expression pipeline и все равно потерять основную пользу Polars:

```python
frame = pl.read_parquet("orders.parquet")
filtered = frame.filter(...)
```

или:

```python
lazy = pl.scan_parquet("orders.parquet")
frame = lazy.collect()
filtered = frame.filter(...)
```

Оба варианта читают данные слишком рано. Optimizer уже не может сдвинуть projection и
predicate к scan, потому что scan произошел до того, как весь pipeline стал видимым.

Задача урока - не просто "переписать на lazy". Нужно доказать, что optimized plan
действительно читает меньше колонок и применяет фильтр на scan, а не материализует все
широкие данные в память.

## Концепция

Lazy execution строит план вычислений. Пока вы не вызвали `collect()`, Polars может
переставлять операции, объединять фильтры и проталкивать работу к источнику данных.

Главные оптимизации этого урока:

| Оптимизация | Что должно быть видно в плане | Почему важно |
|---|---|---|
| Projection pushdown | `PROJECT 11/15 COLUMNS` вместо `PROJECT */15 COLUMNS` | широкие `debug_payload` и `raw_event_json` не читаются |
| Predicate pushdown | `SELECTION:` рядом с `Parquet SCAN` | фильтры по `week_index`, `region`, `is_test_user` применяются у scan |
| Plan visibility | один lazy pipeline до финального `collect()` | optimizer видит весь расчет целиком |

Unoptimized plan полезен как контрольная точка. В нем scan обычно выглядит так:

```text
Parquet SCAN [...]
PROJECT */15 COLUMNS
```

Optimized plan должен показать уже другую форму:

```text
Parquet SCAN [...]
PROJECT 11/15 COLUMNS
SELECTION: [...]
```

Если в optimized plan нет этих признаков, нельзя писать в отчете "pushdown сработал".

## Соберите это

Артефакт урока генерирует широкий Parquet extract и строит lazy pipeline для недельной
витрины `customer_revenue_health_weekly`.

### Шаг 1. Создайте широкий input

```python
frame = generate_customer_revenue_rows(rows=4_800, users=640, seed=42)
```

Вход содержит нужные колонки:

- `week_index`, `week_start`, `platform`, `region`;
- `status`, `gross_revenue_cents`, `refund_amount_cents`;
- `support_ticket_count`, `active_subscription_days`.

И специально содержит ненужные широкие колонки:

- `debug_payload`;
- `raw_event_json`.

Они нужны, чтобы projection pushdown было что отбрасывать.

### Шаг 2. Запишите Parquet

```python
parquet_path = write_parquet_input(frame, "/tmp/polars-lazy-audit")
```

Файл записывается с statistics и row groups. В этом уроке мы не делаем benchmark:
главный artifact - план и проверка формы scan.

### Шаг 3. Постройте lazy scan pipeline

```python
lazy_frame = build_lazy_scan_pipeline(parquet_path)
```

Pipeline начинается с:

```python
pl.scan_parquet(parquet_path)
```

и остается lazy до самого конца. Внутри есть:

- derived columns `net_revenue_cents` и `paid_order`;
- фильтры по `week_index`, `region`, `is_test_user`;
- `group_by().agg(...)`;
- derived metrics;
- rank внутри недели;
- финальный top-3 и sort.

### Шаг 4. Сравните планы

```python
plans = explain_lazy_frame(lazy_frame)
plan_audit = audit_plans(plans)
```

Отчет проверяет:

```text
unoptimized_reads_all_columns = true
optimized_projection_pushdown.reduced = true
optimized_has_selection_at_scan = true
selection_mentions_expected_filters = true
```

Это не идеальный парсер всех планов Polars. Это практичный audit для конкретного
учебного pipeline: он ищет признаки, без которых нельзя утверждать, что optimizer
сдвинул работу к scan.

### Шаг 5. Выполните только после проверки плана

```python
result = lazy_frame.collect()
```

После `collect()` результат сверяется с pandas control:

```python
comparison = compare_outputs(pandas_control, result)
```

Performance-оптимизация без equivalence gate не считается готовой.

## Используйте это

Запустите демонстрационный пример:

```bash
uv run --locked python phases/12-performance/08-lazy-execution/code/main.py
```

Запустите CLI-артефакт:

```bash
uv run --locked python phases/12-performance/08-lazy-execution/outputs/polars_lazy_plan_audit.py \
  --rows 4800 \
  --users 640 \
  --row-group-size 256 \
  --output-dir /tmp/polars-lazy-plan-audit
```

В директории появятся:

- `data/orders.parquet` - широкий вход;
- `optimized-plan.txt` и `unoptimized-plan.txt` - планы Polars;
- `plan-audit.json` - машинная проверка pushdown;
- `polars-lazy-output.csv` и `pandas-control.csv` - сверяемые результаты;
- `report.json` - полный отчет.

Минимально хороший результат:

```text
plan_audit.optimized_projection_pushdown.reduced = true
plan_audit.optimized_has_selection_at_scan = true
source_audit.safe_lazy_source = true
equivalence.matches_pandas = true
interpretation.safe_to_ship = true
```

## Сломайте это

### Замените `scan_parquet` на `read_parquet`

Eager read материализует данные до того, как optimizer увидит pipeline. В source audit
это считается early materialization.

### Вызовите `collect()` в середине

Если сделать:

```python
frame = pl.scan_parquet(path).collect()
```

дальше вы уже работаете с eager `DataFrame`. Фильтры после этого не могут стать
predicate pushdown.

### Добавьте `map_elements`

Python UDF может быть нужен в редких случаях, но он делает часть логики непрозрачной для
optimizer. В этом уроке такой pattern блокирует shipping, пока нет отдельного измерения
и объяснения.

### Читайте только optimized plan

Optimized plan показывает итоговую форму, но unoptimized plan полезен для сравнения. Он
показывает, какие фильтры и projection были в исходной цепочке до оптимизации.

## Проверьте это

Точечная проверка урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/08-lazy-execution/tests
```

Проверка артефакта:

```bash
uv run --locked python phases/12-performance/08-lazy-execution/outputs/polars_lazy_plan_audit.py \
  --rows 1200 \
  --users 160 \
  --output-dir /tmp/polars-lazy-smoke
```

Контракт отчета:

- unoptimized plan читает все колонки;
- optimized plan читает меньше колонок;
- optimized plan содержит `SELECTION` у `Parquet SCAN`;
- selection включает ожидаемые фильтры;
- source audit не находит ранний `collect()` или Python UDF;
- lazy result совпадает с pandas control;
- output grain `week_start, platform, region` уникален.

## Поставьте результат

Именованный артефакт урока - CLI `polars-lazy-plan-audit`:

```bash
uv run --locked python phases/12-performance/08-lazy-execution/outputs/polars_lazy_plan_audit.py \
  --rows 4800 \
  --users 640 \
  --output-dir /tmp/polars-lazy-plan-audit
```

Его можно использовать как шаблон ревью Polars lazy pipeline:

1. начните с `scan_*`, а не `read_*`;
2. держите pipeline lazy до финального `collect`;
3. сохраняйте optimized и unoptimized plans;
4. проверяйте projection/predicate pushdown по тексту плана;
5. блокируйте early materialization и Python UDF patterns;
6. сверяйте результат с контрольным расчетом.

## Упражнения

1. Добавьте фильтр по `platform == "android"` и проверьте, появился ли он в `SELECTION`.
2. Добавьте еще одну широкую неиспользуемую колонку и убедитесь, что optimized plan не
   увеличил число читаемых колонок.
3. Временно вставьте `collect()` после `scan_parquet`, затем перепишите обратно на lazy
   pipeline и сравните audit.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Lazy execution | Просто отложенный запуск ради удобства | Построение плана, который optimizer может переписать до чтения данных |
| `scan_parquet` | То же самое, что `read_parquet` | Lazy scan, который может получить projection/predicate pushdown |
| `collect()` | Безопасная промежуточная точка | Граница материализации; после нее optimizer уже не видит downstream work |
| Projection pushdown | Выбор колонок после чтения | Проталкивание нужного набора колонок в scan |
| Predicate pushdown | Фильтр после DataFrame materialize | Проталкивание фильтра к источнику данных или scan |

## Дополнительное чтение

- [Polars: Lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) - прочитайте объяснение lazy query, `collect()` и `explain()`.
- [Polars: Lazy optimizations](https://docs.pola.rs/user-guide/lazy/optimizations/) - используйте список оптимизаций как чеклист для projection и predicate pushdown.
- [Polars: Parquet IO](https://docs.pola.rs/user-guide/io/parquet/) - разберите `scan_parquet` и параметры чтения Parquet как источник lazy pipeline.
- [Polars: User-defined Python functions](https://docs.pola.rs/user-guide/expressions/user-defined-python-functions/) - прочитайте предупреждения про Python UDF, чтобы понимать, почему они блокируются в audit.
