# Ibis как переносимый DataFrame API

> Переносимый expression уменьшает дублирование логики, но не отменяет различия
> backend, планов и runtime.

**Тип:** Case
**Треки:** Data, ML
**Пререквизиты:** `12-performance/10-interoperability`
**Время:** ~120 минут
**Результат:** выражает один performance pipeline переносимым Ibis API, сравнивает
backend-specific планы и измерения с pandas, DuckDB и Polars и оформляет решение о
движке с ограничениями.

## Цели обучения

- Построить прозрачный ручной baseline и reviewed tiny expected output.
- Выразить общий relational core одним Ibis expression.
- Выполнить этот expression на Ibis DuckDB и Ibis Polars.
- Сравнить пять реализаций только после exact equivalence gate.
- Сохранить SQL, LazyFrame plans, raw runs, environment и ограничения.
- Найти backend divergence и не маскировать его portability-абстракцией.
- Выпустить проверяемый engine decision с measurement и limitation links.

## Проблема

К концу фазы у нас есть рабочие pipeline на pandas, DuckDB и Polars. Но production
выбор редко заканчивается фразой "этот движок быстрее":

- локально быстрее Polars, а в другом окружении нужен SQL backend;
- DuckDB хорошо читает Parquet, но команда поддерживает несколько warehouses;
- pandas API знаком, но sample уже приближается к memory budget;
- копирование одной и той же бизнес-логики на три API создает semantic drift;
- переносимый API обещает единый код, но backend поддерживают разные операции.

Ibis решает часть задачи: expression описывается один раз, а выполнение делегируется
backend. Но если воспринимать Ibis как "один движок для всего", можно потерять именно ту
наблюдаемость, которую мы строили всю фазу.

Финальный урок отвечает на более строгий вопрос:

> Можно ли сохранить один tested relational core и при этом выбирать backend по
> измерениям, планам и ограничениям?

## Концепция

Ibis expression - это декларативный граф операций. Сам Ibis не является вычислительным
движком:

```text
Ibis expression
├── DuckDB backend -> SQL -> DuckDB runtime
└── Polars backend -> LazyFrame -> Polars runtime
```

Переносимость имеет уровни:

| Уровень | Что проверяем |
|---|---|
| Expression | Одинаковая логика filter/mutate/group/aggregate/case |
| Compilation | Backend может перевести все операции |
| Semantics | Результат совпадает с reviewed control |
| Plan | Scan, filter и aggregate видны в backend-specific плане |
| Runtime | Измерение проведено в одинаковой границе |
| Operations | Непереносимые окна/UDF/fallback явно перечислены |

Один expression не означает одинаковый physical plan. Это хорошо: backend должен
использовать собственный optimizer. Плохо только скрывать различия и считать успешную
компиляцию доказательством корректности или скорости.

## Соберите это

Итоговый артефакт создает
`performance-benchmark-package/` для pipeline
`customer_revenue_health_weekly`.

### Шаг 1. Зафиксируйте ручной механизм

`run_manual_reference` проходит eligible orders циклом и хранит state по grain:

```text
week_start, platform, region
```

Partial state содержит:

```text
orders
paid_orders
gross_revenue_cents
refund_amount_cents
net_revenue_cents
support_ticket_count
active_subscription_days
```

Производные метрики считаются после aggregation:

```text
revenue_per_paid_order_cents
refund_rate_bp
health_band
```

Отдельные десять строк `TINY_ROWS` имеют вручную проверенный `TINY_EXPECTED`. Этот gate
нужен до сравнения библиотек: если ошибся сам reference, пять одинаковых движков лишь
подтвердят одну ошибку.

### Шаг 2. Постройте portable Ibis core

Функция:

```python
build_ibis_pipeline(table)
```

использует только общий набор:

- `filter`;
- `mutate`;
- `group_by().aggregate()`;
- `nunique` и `sum`;
- integer floor division;
- `ibis.ifelse` и `ibis.cases`;
- `select` и `order_by`.

Один и тот же Python-код вызывается для таблиц двух backend:

```python
duckdb_table = ibis.duckdb.connect().read_parquet(path)
polars_table = ibis.polars.connect().read_parquet(path)

duckdb_expr = build_ibis_pipeline(duckdb_table)
polars_expr = build_ibis_pipeline(polars_table)
```

Компиляция различается:

```text
Ibis DuckDB -> SQL string
Ibis Polars -> polars.LazyFrame
```

Пакет сохраняет оба результата в `profiles/`.

### Шаг 3. Проверьте portability failure

Дополнительный probe добавляет:

```python
ibis.dense_rank().over(
    ibis.window(
        group_by="week_start",
        order_by=ibis.desc(net_revenue_cents),
    )
)
```

На зафиксированных версиях:

- DuckDB backend компилирует окно;
- Polars backend Ibis `12.0.0` возвращает `OperationNotDefinedError`.

Это не повод удалить Ibis. Это граница portable core:

```text
shared core -> portable
weekly dense rank -> backend-specific fallback
```

Артефакт сохраняет error type и policy. Нельзя ловить исключение и молча менять смысл
pipeline.

### Шаг 4. Подготовьте пять сравнимых runners

Benchmark включает:

1. `pandas`;
2. `duckdb_native`;
3. `polars_native`;
4. `ibis_duckdb`;
5. `ibis_polars`.

Setup выполняется заранее:

- deterministic generation;
- Parquet write;
- backend connections;
- expression creation;
- compilation.

Timed section одинаков:

```text
Parquet scan -> compute -> normalized pandas handoff
```

Так измерение включает цену реального локального pipeline, но не смешивается с
генерацией данных или установкой connection.

### Шаг 5. Поставьте equivalence gate

До warm-up каждый runner выполняется один раз. Результат нормализуется:

- одинаковый column order;
- string dimensions;
- nullable integer metrics;
- стабильная сортировка по grain.

Если хотя бы один checksum расходится:

```text
equivalence gate failed before timing
```

и package не строится.

### Шаг 6. Измерьте без ложной точности

Каждый engine получает:

- минимум один warm-up;
- минимум три measured runs;
- `perf_counter`;
- `process_time`;
- result checksum каждого run.

В `summary.csv` записываются min, median, max и mean. Selection rule использует median,
но raw measurements не перезаписываются.

Cache policy честная:

```text
warm filesystem cache after warm-up
```

Это не cold-cache benchmark и не переносимый результат для другой машины.

### Шаг 7. Свяжите решение с evidence

Сначала выбирается самый быстрый эквивалентный native backend. Затем проверяется Ibis
overhead:

```text
ibis median / native median <= 1.25
```

Если portable core проходит оба backend и overhead не больше 25%, допустимо решение:

```text
use_ibis_over_backend
```

Иначе выбирается native pandas, DuckDB или Polars. Результат зависит от машины и
профиля данных, поэтому урок не зашивает победителя.

Каждый decision содержит:

- measurement IDs;
- profile ID;
- plan checks;
- limitation IDs.

## Используйте это

Запустите компактный пример:

```bash
uv run --locked python phases/12-performance/11-ibis/code/main.py
```

Соберите sample package:

```bash
uv run --locked python \
  phases/12-performance/11-ibis/outputs/performance_benchmark_packager.py \
  --profile sample \
  --repeat 5 \
  --warmup 1 \
  --output-dir /tmp/performance-benchmark-package
```

Для быстрого smoke:

```bash
uv run --locked python \
  phases/12-performance/11-ibis/outputs/performance_benchmark_packager.py \
  --profile tiny \
  --rows 1200 \
  --users 160 \
  --repeat 3 \
  --row-group-size 256 \
  --output-dir /tmp/performance-benchmark-tiny
```

`large` запрещен без явного подтверждения:

```bash
... --profile large --allow-large ...
```

Это защищает обычный запуск от случайной генерации миллиона широких строк.

## Сломайте это

### Измеряйте до equivalence

Измените `net_revenue_cents` у одного runner на одну копейку. Gate обязан остановить
benchmark до первого warm-up.

### Сравнивайте разный scope

Если pandas включает `read_parquet`, а Polars измеряет уже собранный DataFrame, это
benchmark разных задач.

### Считайте один run доказательством

Cold start, filesystem cache и соседняя нагрузка могут поменять порядок движков. Один
run не используется для selection rule.

### Назовите Ibis универсальным backend

Ibis делегирует выполнение. SQL string и Polars LazyFrame имеют разные optimizers,
операции и failure modes.

### Спрячьте rank fallback

Автоматическая замена dense rank другой операцией меняет output contract. Fallback
должен быть отдельным backend-specific кодом и тестом.

### Назовите tracemalloc полной памятью

`tracemalloc` видит Python allocations, но может пропустить native memory DuckDB,
Arrow и Polars. Package сохраняет это ограничение как `L2`.

## Проверьте это

Точечные тесты урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/11-ibis/tests -v
```

Контракт готового package:

- reviewed tiny expected output совпадает с manual reference;
- все пять engines проходят exact equivalence до timing;
- каждый engine имеет warm-up и минимум три raw runs;
- каждый measured run сохраняет тот же result checksum;
- DuckDB и Polars plans содержат scan/filter/aggregate evidence;
- Ibis DuckDB компилируется в SQL;
- Ibis Polars компилируется в `LazyFrame`;
- portable core поддерживается обоими backend;
- dense-rank divergence воспроизводится и документируется;
- engine decision входит в разрешенный словарь;
- decision ссылается на measurements и limitations;
- SHA-256 manifest проходит повторную проверку.

## Поставьте результат

Именованный артефакт:

```text
performance-benchmark-packager
```

Он выпускает:

```text
performance-benchmark-package/
├── benchmark-plan.json
├── data/
│   └── orders.parquet
├── data-contract/
│   ├── sources.json
│   ├── output-contract.json
│   └── dtype-policy.json
├── data-layout/
│   ├── parquet-layout.json
│   ├── partition-summary.json
│   └── row-group-summary.json
├── pipelines/
│   ├── pandas_pipeline.py
│   ├── duckdb_pipeline.sql
│   ├── polars_pipeline.py
│   └── ibis_pipeline.py
├── profiles/
│   ├── python-profile.json
│   ├── memory-profile.json
│   ├── duckdb-plan.json
│   ├── polars-plan.txt
│   ├── ibis-duckdb.sql
│   └── ibis-polars-plan.txt
├── measurements/
│   ├── raw-runs.csv
│   ├── summary.csv
│   └── environment.json
├── equivalence/
│   ├── output-checks.json
│   ├── reconciliation.csv
│   └── tiny-expected-output.json
├── reports/
│   ├── engine-decision.json
│   ├── engine-decision.md
│   ├── portability-audit.json
│   ├── portability-audit.md
│   └── limitations.md
├── report.json
└── manifest.json
```

Package можно передать на другую машину и повторить с теми же profile, rows, seed,
warm-up и repeat. Сравнивать два package можно только после проверки environment и cache
policy.

## Упражнения

1. Реализуйте backend-specific dense rank после portable core и добавьте отдельный
   equivalence test для DuckDB и Polars.
2. Повторите benchmark с явным `threads=1`, затем с доступным числом ядер. Не смешивайте
   результаты в одной summary.
3. Добавьте второй Parquet layout и разрешите `redesign_layout`, только если оба layout
   имеют одинаковый output contract и отдельные measurement IDs.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Ibis expression | Универсальный physical plan | Декларативный граф, который backend переводит в собственное представление |
| Backend | Просто формат вывода | Реальный runtime и compiler со своими возможностями |
| Portable core | Весь pipeline обязан работать везде | Подмножество операций, проверенное на выбранных backend |
| Backend divergence | Баг, который нужно скрыть | Наблюдаемое различие support/semantics, требующее policy |
| Equivalence gate | Проверка после benchmark | Блокирующая проверка до timing |
| Engine decision | Название самого быстрого run | Решение по median, plans, portability и limitations |

## Дополнительное чтение

- [Ibis: Installation](https://ibis-project.org/install) - проверьте extras backend и принцип установки только нужных движков.
- [Ibis: Backends](https://ibis-project.org/backends) - используйте support matrix перед обещанием переносимости конкретной операции.
- [Ibis: DuckDB backend](https://ibis-project.org/backends/duckdb) - изучите `read_parquet`, compilation и локальное выполнение SQL.
- [Ibis: Polars backend](https://ibis-project.org/backends/polars) - сравните LazyFrame execution и список поддержанных операций.
- [Ibis 12.0 release notes](https://ibis-project.org/release_notes.html#version-12-0-0) - зафиксируйте изменения версии, на которой построен portability audit.
