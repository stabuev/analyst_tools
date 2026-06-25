# Проект фазы 12: Производительность аналитики

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую performance-задачу, модель данных, роли инструментов и контракт итогового
multi-engine benchmark package.

## Результат фазы

Студент перестает выбирать движок по моде или одному удачному замеру. Он берет один
аналитический pipeline, фиксирует контракт результата, воспроизводимо измеряет wall time,
CPU, память, IO и план выполнения, а затем объясняет, где pandas достаточно, где нужен
DuckDB, где выигрывает Polars, а где переносимый API вроде Ibis добавляет пользу или
лишнюю прослойку.

Фаза учит принимать performance-решения как аналитические решения:

- измерять только сравнимые pipelines с одинаковым результатом;
- отделять setup, IO, compute, конвертацию форматов и публикацию результата;
- читать планы выполнения, а не только секундомер;
- уменьшать объем данных через layout, projection, predicate pushdown и dtype policy;
- проверять, что оптимизация не сломала grain, типы, NULL semantics, timezone и деньги;
- оформлять выбор движка с ограничениями, бюджетом памяти и сценариями пересмотра.

Фаза состоит из четырех последовательных блоков:

1. `12/01`-`12/03`: корректный benchmark, CPU/memory profiling, memory budget и dtype
   policy.
2. `12/04`-`12/06`: Parquet layout, Arrow memory model, DuckDB query plans и
   out-of-core execution.
3. `12/07`-`12/10`: Polars expressions, lazy optimizer, streaming/chunked processing и
   interoperability между pandas, Arrow, DuckDB и Polars.
4. `12/11`: интеграционный multi-engine benchmark с Ibis portability audit и
   обоснованным engine decision.

Суммарная длительность - 915 минут, или 15,25 часа.

## Границы содержания

- **Не повтор pandas, SQL и reliability.** Фаза опирается на DataFrame operations из
  фазы 03, DuckDB query plans из фазы 04 и quality gates из фазы 07. Здесь главный вопрос
  - как измерить и изменить стоимость уже понятного расчета, не потеряв корректность.
- **Не курс распределенных систем.** Spark, Dask, Ray, Flink, кластеры, shuffle-сети,
  autoscaling и cloud cost governance остаются вне обязательной фазы. Студент работает с
  локальными single-node инструментами и понимает момент, когда локального подхода уже
  мало.
- **Не optimization theater.** Микробенчмарки ради красивых чисел, случайные
  `%%timeit`, сравнение разных результатов и выводы по одному прогону считаются failure
  mode. Каждый benchmark обязан иметь equivalence gate и environment report.
- **Не низкоуровневый курс CPU.** SIMD, cache lines, vectorized execution internals,
  allocator tuning и C/Rust extension development упоминаются как контекст, но не
  становятся практической целью аналитика.
- **Не warehouse administration.** Partition pruning, row groups, memory limits и
  temp spill изучаются локально. Cloud warehouse slots, cluster sizing, permissions,
  storage tiers и production incident response остаются за границей.
- **Не ML training performance.** Фаза полезна ML-маршруту как подготовка табличных
  данных и feature tables, но не оптимизирует обучение моделей, GPU, CatBoost,
  hyperparameter search или inference serving.
- **Не polished delivery.** Итоговый package содержит отчет и рекомендации по движку, но
  заказчицкая упаковка в memo, dashboard, приложение или презентацию остается фазе 17.

## Роли инструментов

Новые зависимости не добавляются на этапе проектирования. В корневой locked environment
уже есть pandas, DuckDB и PyArrow. Polars и Ibis добавляются только вместе с первым
уроком, который реально запускает соответствующий инструмент, после повторной проверки
актуальной официальной документации и lock-файла.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| Python `timeit`, `cProfile`, `pstats`, `tracemalloc` | Минимальный benchmark/profiling harness, repeat policy, CPU call graph и Python allocation snapshots | Профилирование native memory всех C/Rust extensions без дополнительных инструментов |
| pandas | Базовый in-memory pipeline, dtype tuning, chunking baseline и контрольная семантика результата | Новый обзор pandas API и работа с данными больше памяти как основная стратегия |
| PyArrow / Apache Arrow | In-memory columnar buffers, null bitmaps, offsets, chunks, dictionary encoding, Parquet IO и copy audit | Arrow Flight, C++ development, GPU/CUDA и distributed zero-copy transport |
| DuckDB | SQL baseline, Parquet pushdown, `EXPLAIN`/`EXPLAIN ANALYZE`, memory/temp settings и larger-than-memory workloads | Cloud warehouse, dbt orchestration, server administration и DuckDB internals |
| Polars | Expression DSL, lazy scan, optimizer plans, streaming execution и быстрый local DataFrame engine | Polars Cloud, GPU beta, Rust API и distributed execution |
| Ibis | Переносимое выражение pipeline, backend comparison, SQL generation и portability audit | Полная замена backend-specific reasoning и скрытие различий dialect/optimizer/runtime |
| NumPy | Детерминированная генерация данных, контрольные векторы и независимые sanity checks | Новый курс численных вычислений |
| Pandera / Pydantic | Контракты входов, output schema, benchmark plan и selection rule | Production data quality platform и web/API schemas |
| pytest | Behavioral tests для equivalence, profiling reports, plan assertions и final package | Повтор базового pytest/CI из фазы 01 |

Проверенные официальные ориентиры:

- [Python `timeit`](https://docs.python.org/3/library/timeit.html) - repeat/autorange,
  `perf_counter`, process time и предупреждения о шуме измерений.
- [Python profilers](https://docs.python.org/3/library/profile.html) - `cProfile` и
  `pstats` для CPU call graph и ограничений deterministic profiling.
- [Python `tracemalloc`](https://docs.python.org/3/library/tracemalloc.html) - tracing
  Python allocations, snapshots, peak size и ограничение на native allocations.
- [pandas: Scaling to large datasets](https://pandas.pydata.org/docs/user_guide/scale.html)
  - load less data, efficient dtypes, chunking и момент перехода к другим библиотекам.
- [pandas: PyArrow Functionality](https://pandas.pydata.org/docs/user_guide/pyarrow.html)
  - Arrow-backed data types и границы pandas/PyArrow interoperability.
- [Apache Arrow Columnar Format](https://arrow.apache.org/docs/format/Columnar.html) -
  физическая columnar layout, buffers, validity bitmaps и nested data.
- [PyArrow memory and IO](https://arrow.apache.org/docs/python/memory.html) - buffers,
  memory pools, allocated bytes и IO interfaces.
- [PyArrow Parquet](https://arrow.apache.org/docs/python/parquet.html) - чтение/запись
  Parquet, metadata, row groups и dataset-level access.
- [DuckDB Parquet](https://duckdb.org/docs/current/data/parquet/overview) - partial
  reading, projection/filter pushdown, row groups и параметры записи.
- [DuckDB workload tuning](https://duckdb.org/docs/current/guides/performance/how_to_tune_workloads)
  - threads, row groups, temp spill, blocking operators, out-of-core scope и profiling.
- [Polars expressions and contexts](https://docs.pola.rs/user-guide/concepts/expressions-and-contexts/)
  - expression DSL, contexts и почему выражения являются строительными блоками query
  engine.
- [Polars lazy API](https://docs.pola.rs/user-guide/concepts/lazy-api/) - deferred
  execution, optimizer, `explain`, projection и predicate pushdown.
- [Polars lazy optimizations](https://docs.pola.rs/user-guide/lazy/optimizations/) -
  набор оптимизаций, которые студент должен увидеть в планах, а не просто предполагать.
- [Polars streaming](https://docs.pola.rs/user-guide/concepts/streaming/) - потоковое
  выполнение и inspection streaming query.
- [Ibis](https://ibis-project.org/) - portable Python dataframe API, больше 20 backends,
  локальный DuckDB default и возможность inspect generated SQL.
- [Ibis DuckDB backend](https://ibis-project.org/backends/duckdb) - локальный backend,
  connection options и границы переносимости.

## Единая performance-задача и данные

Фаза использует ту же вымышленную продуктовую вселенную: подписочный сервис с
маркетплейсом дополнительных товаров, событиями, подписками и поддержкой. Рабочий вопрос
интеграционного проекта: «Еженедельный customer revenue health pipeline вырос из сотен
тысяч строк до десятков миллионов. Какой движок и layout выбрать, чтобы расчет был
быстрым, воспроизводимым и не менял смысл метрик?»

Фаза не зависит от runtime-файлов фаз 08-11. Она создает автономный совместимый extract,
чтобы уроки проходились независимо, но семантика пользователей, событий, заказов,
подписок и обращений остается общей для курса.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `users` | один зарегистрированный пользователь | `user_id` |
| `events` | одно клиентское или серверное событие | `event_id` |
| `orders` | один заказ или платеж маркетплейса | `order_id` |
| `order_items` | одна товарная позиция заказа | `order_id, line_number` |
| `subscriptions` | один период подписки | `subscription_id` |
| `support_tickets` | одно обращение пользователя | `ticket_id` |
| `refunds` | один refund по заказу | `refund_id` |
| `currency_rates` | один курс валюты на дату | `currency, rate_date` |
| `calendar` | один календарный день с business attributes | `date` |

Performance pipeline строит недельную витрину:

```text
customer_revenue_health_weekly
grain: user_id, week_start
metrics:
  activated_7d
  paid_orders
  gross_revenue_rub
  refund_amount_rub
  net_revenue_rub
  active_subscription_days
  support_ticket_count
  first_paid_order_age_days
dimensions:
  platform
  acquisition_channel
  region
  plan
  signup_cohort
```

Профили данных:

- `tiny`: десятки строк в Git для ручной проверки output contract, dtype policy,
  pushdown examples и engine equivalence.
- `sample`: сотни тысяч строк, генерируются локально для обычных benchmarks и планов.
- `large`: миллионы или десятки миллионов строк, генерируются локально по запросу для
  DuckDB out-of-core, Polars lazy/streaming и final benchmark; в Git не хранится.

Заложенные свойства и failure modes:

- benchmark включает генерацию данных или import setup и поэтому сравнивает не pipeline;
- pandas, DuckDB и Polars возвращают разные строки из-за отличий NULL, timezone,
  category ordering или floating-point aggregation;
- один прогон считается доказательством, хотя warm-up, cache и соседние процессы
  создают шум;
- среднее скрывает cold-start или outlier, а report не показывает raw measurements;
- memory report считает только Python heap и пропускает native allocations;
- dtype downcast переполняет `order_id`, теряет копейки или меняет nullable semantics;
- `category` экономит память на low-cardinality поле, но ломается на новых категориях;
- Parquet layout слишком широкий, row groups не подходят под threads, partitions создают
  small files или не совпадают с частыми фильтрами;
- projection/predicate pushdown не происходит из-за чтения всех колонок до фильтра;
- Python UDF, ранний materialize/collect или conversion to pandas блокирует optimizer;
- DuckDB spill пишет во временную директорию с недостаточным местом;
- несколько blocking operators в одном запросе создают OOM даже при включенном spill;
- Polars eager pipeline читает лишние колонки, а lazy pipeline меняет порядок операций;
- streaming/chunking применяется к non-associative calculation и меняет результат;
- обмен pandas/Arrow/Polars/DuckDB скрыто копирует данные или меняет schema metadata;
- Ibis expression выглядит переносимо, но backend-specific dialect или unsupported
  operation требует явного fallback.

## Контракт benchmark scenario

Каждый benchmark в фазе описывается machine-readable scenario:

```text
scenario_id
business_question
pipeline_name
pipeline_version
dataset_profile
input_paths
input_format
layout_policy
expected_output_contract
scale_rows
memory_budget_mb
engines
engine_versions
thread_policy
cache_policy
warmup_runs
measured_runs
timer
memory_metric
cpu_metric
io_metric
plan_checks
equivalence_checks
quality_gates
selection_rule
known_limitations
rerun_instructions
```

Сценарий запрещает сравнивать несравнимое. Если pipeline не имеет output contract,
equivalence check, versions, cache policy и raw measurement table, его результат нельзя
использовать для выбора движка.

## Интеграционный мини-проект

`12/11` собирает поставку:

```text
performance-benchmark-package/
├── benchmark-plan.json
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
│   └── polars-plan.txt
├── measurements/
│   ├── raw-runs.csv
│   ├── summary.csv
│   └── environment.json
├── equivalence/
│   ├── output-checks.json
│   └── reconciliation.csv
├── reports/
│   ├── engine-decision.md
│   ├── portability-audit.md
│   └── limitations.md
└── manifest.json
```

Проект обязан:

- генерировать `tiny` и `sample` профили детерминированно, а `large` - только по явной
  команде;
- строить один и тот же `customer_revenue_health_weekly` результат в pandas, DuckDB и
  Polars;
- проверять output equivalence до интерпретации performance numbers;
- фиксировать Python, OS, CPU, memory budget, versions, threads, input size и cache
  policy;
- сохранять raw measurements, summary и выбранную статистику без перезаписи исходных
  прогонов;
- показывать `EXPLAIN`/`EXPLAIN ANALYZE` для DuckDB и optimized lazy plan для Polars;
- доказывать или опровергать projection/predicate pushdown на конкретном layout;
- отделять стоимость чтения, вычисления, конвертации и записи результата;
- проверять, что dtype/layout/interoperability optimization не меняет бизнес-смысл;
- выражать pipeline через Ibis и явно помечать backend-specific divergences;
- выпускать engine decision из ограниченного набора: `keep_pandas`, `use_duckdb`,
  `use_polars`, `use_ibis_over_backend`, `redesign_layout`, `split_pipeline`;
- связывать каждую рекомендацию с measurement id, profile id, plan check и limitation;
- публиковать SHA-256 manifest всех переданных файлов.

## Проверяемость

- Tiny-profile содержит ручные ожидаемые ответы для weekly revenue health mart.
- Benchmark tests проверяют, что setup не входит в timed section, есть warm-up, raw runs,
  environment report и минимум один equivalence gate.
- Profiling tests проверяют наличие CPU hot spots, peak memory/RSS или явной пометки
  ограничения инструмента и actionable classification.
- Dtype tests сравнивают memory reduction с semantic checks: overflow, precision,
  nullable policy, category vocabulary и timezone.
- Parquet tests проверяют row group metadata, partitions, selected columns, filters и
  план с pushdown evidence.
- Arrow tests инспектируют buffers/null bitmap/offsets/chunks и фиксируют copy vs
  zero-copy conversion.
- DuckDB tests запускают workload с временной директорией, проверяют plan/profile JSON,
  blocking operators и корректную обработку memory budget.
- Polars tests сверяют expression pipeline с pandas/DuckDB baseline и проверяют, что
  lazy plan не содержит раннего materialize.
- Streaming tests различают associative partial aggregates и операции, требующие полной
  координации.
- Interoperability tests проверяют schema, nulls, timestamps, categories и факт
  копирования на границах pandas/Arrow/DuckDB/Polars.
- Final package test проверяет структуру, manifest, checksum, engine-decision links,
  raw measurements, equivalence report и отсутствие вывода без measurement evidence.
