# Проект фазы 11: Analytics Engineering

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую analytics engineering задачу, модель данных, роли инструментов и контракт
итогового локального dbt-duckdb проекта.

## Результат фазы

Студент превращает набор SQL-запросов и ручных проверок в управляемый граф аналитических
моделей: raw sources объявлены явно, преобразования разложены по слоям, зависимости
строятся через `source()` и `ref()`, витрина проверяется data tests и бизнес-reconciliation,
а документация и lineage позволяют потребителю понять, откуда взялось каждое поле.

Фаза не учит «запустить dbt ради dbt». Она учит принимать инженерные решения:

- где проходит граница между raw, staging, intermediate и mart;
- какой grain и primary key несет каждая модель;
- какие проверки являются contract gate, а какие остаются warning diagnostics;
- когда view, table, ephemeral, incremental model или snapshot соответствует задаче;
- где Jinja macro уменьшает риск, а где прячет бизнес-логику;
- как доказать, что опубликованная витрина воспроизводима и задокументирована.

Фаза состоит из четырех последовательных блоков:

1. `11/01`-`11/03`: data layers, dbt project contract, sources, refs и dependency graph.
2. `11/04`-`11/06`: модели, materializations, data tests и аккуратные Jinja macros.
3. `11/07`-`11/10`: incremental models, snapshots, documentation, lineage и SQLFluff.
4. `11/11`: интеграционный локальный dbt-duckdb проект.

Суммарная длительность - 900 минут, или 15 часов.

## Границы содержания

- **Не повтор SQL и DuckDB.** Фаза опирается на grain, joins, CTE, windows, SQL/Python
  boundary и query plans из фазы 04. Здесь главный вопрос - как организовать SQL как
  версионируемый граф моделей с контрактами, тестами и lineage.
- **Не повтор надежной аналитики.** Инварианты, Pandera/Pydantic, SQL checks, golden
  datasets и atomic publication пройдены в фазе 07. Здесь эти практики переносятся в dbt
  resource model: sources, models, tests, snapshots, docs artifacts и run results.
- **Не data engineering orchestrator.** Airflow, Dagster, Prefect, retries на уровне
  workflow, SLA alerting, backfill orchestration и production access control остаются за
  границей фазы. Студент собирает локальный reproducible project и понимает, что именно
  должен запускать внешний scheduler.
- **Не cloud warehouse курс.** BigQuery, Snowflake, Redshift, Databricks и permissions
  обсуждаются как production контекст, но упражнения используют DuckDB через
  `dbt-duckdb`, чтобы курс работал локально и без платного аккаунта.
- **Не Semantic Layer и BI modeling.** Metrics, semantic models, MetricFlow, dbt Mesh,
  exposures как governance на уровне компании и BI dashboard delivery остаются
  факультативами или фазой 17. В фазе 11 exposures нужны только как downstream contract.
- **Не курс performance engineering.** Materialization choice, incremental cutoff и
  source freshness рассматриваются с точки зрения корректности и стоимости повторного
  запуска. Глубокие benchmarks, Arrow memory, Polars, out-of-core и pushdown остаются
  фазе 12.
- **Не polished stakeholder delivery.** Итоговая витрина документирована и проверена, но
  презентация, memo, dashboard, приложение и scheduled delivery остаются фазе 17.

## Роли инструментов

Зависимости добавляются в корневой locked environment только вместе с первым уроком,
который реально запускает инструмент. На 21 июня 2026 года официальная документация dbt
показывает ветку v2.0 и одновременно активную поддержку Python-ветки dbt Core v1.11 до
18 декабря 2026. Для курса проектное решение такое: фаза учит переносимые dbt concepts и
локально исполняемый проект через `dbt-core`/`dbt-duckdb` в `uv`, пока это самый
воспроизводимый путь для open course без внешней платформы.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| dbt Core/local CLI | `parse`, `compile`, `run`, `test`, `docs generate`, `source freshness`, artifacts и node selection | dbt Cloud/platform, release tracks, Mesh governance и hosted deployment |
| dbt-duckdb | Локальный profile, in-memory/file database, чтение CSV/Parquet sources и portable warehouse для уроков | MotherDuck, cloud object storage, secrets manager и external catalogs как обязательная практика |
| DuckDB | SQL engine для моделей, independent reconciliation и проверка physical tables/views | Отдельный курс optimizer/performance и warehouse administration |
| SQLFluff | Единый стиль SQL, lint templated dbt models и CI report | Семантическая валидация модели и автоматическое исправление бизнес-логики |
| PyYAML/Pydantic | Аудит project/profile/contracts, source specs, run artifacts и machine-readable reports | Замена dbt manifest или production metadata platform |
| pytest | Behavioral tests для локальных CLI-артефактов, compiled SQL, reports и final package | Повтор базового pytest и CI из фазы 01 |

Проверенные официальные ориентиры:

- [dbt: About dbt projects](https://docs.getdbt.com/docs/build/projects) - структура
  проекта, `dbt_project.yml`, resources и проектные директории.
- [dbt: About dbt versions](https://docs.getdbt.com/docs/dbt-versions) - различие
  Fusion/Core v2 и dbt Core v1, active/critical/EOL support и adapter plugin versions.
- [dbt: Sources](https://docs.getdbt.com/docs/build/sources) - объявление raw tables,
  `source()`, source tests, freshness и lineage.
- [dbt: ref](https://docs.getdbt.com/reference/dbt-jinja-functions/ref) - модельные
  зависимости, full relation names и автоматический порядок запуска.
- [dbt: Materializations](https://docs.getdbt.com/docs/build/materializations) - view,
  table, incremental, ephemeral и materialized view как стратегии сохранения моделей.
- [dbt: Data tests](https://docs.getdbt.com/docs/build/data-tests) - generic/singular
  assertions, failing records и встроенные проверки `not_null`, `unique`, relationships
  и accepted values.
- [dbt: Jinja and macros](https://docs.getdbt.com/docs/build/jinja-macros) - SQL +
  Jinja, compiled SQL, macros, macro documentation и рекомендация держать модели
  читаемыми.
- [dbt: Incremental models](https://docs.getdbt.com/docs/build/incremental-models) -
  `is_incremental()`, filtering, `unique_key`, full refresh и schema change policy.
- [dbt: Snapshots](https://docs.getdbt.com/docs/build/snapshots) - SCD type 2 история
  mutable source tables.
- [dbt: Documentation](https://docs.getdbt.com/docs/build/documentation) - descriptions,
  generated docs website, manifest/catalog metadata и DAG.
- [dbt: DuckDB setup](https://docs.getdbt.com/docs/local/connect-data-platform/duckdb-setup)
  - local profile, in-memory/file database, threads, extensions и attach.
- [SQLFluff: dbt templater](https://docs.sqlfluff.com/en/stable/configuration/templating/dbt.html)
  - trade-off между `dbt` и `jinja` templaters, profile/project configuration и CI
  implications.

## Единая analytics engineering задача и данные

Фаза использует ту же вымышленную продуктовую вселенную: подписочный сервис с
маркетплейсом дополнительных товаров, событиями, подписками и поддержкой. Рабочий вопрос
интеграционного проекта: «Собрать документированную витрину customer revenue health,
которой продуктовая и финансовая команды могут доверять при анализе активации, выручки,
подписок, возвратов и обращений в поддержку».

Фаза не зависит от runtime-файлов фаз 08-10. Она создает собственный совместимый extract,
чтобы уроки проходились автономно, но семантика полей остается единой.

Raw sources:

| Source | Grain | Ключ |
|---|---|---|
| `raw_users` | один зарегистрированный пользователь | `user_id` |
| `raw_events` | одно клиентское или серверное событие | `event_id` |
| `raw_orders` | один заказ или платеж маркетплейса | `order_id` |
| `raw_order_items` | одна строка заказа | `order_id, line_number` |
| `raw_subscriptions` | один период подписки | `subscription_id` |
| `raw_support_tickets` | одно обращение пользователя | `ticket_id` |
| `raw_refunds` | один refund по заказу | `refund_id` |
| `raw_currency_rates` | один курс валюты на дату | `currency, rate_date` |

Целевые модели:

| Слой | Примеры моделей | Назначение |
|---|---|---|
| `staging` | `stg_users`, `stg_orders`, `stg_order_items`, `stg_subscriptions`, `stg_events` | Нормализация имен, типов, timezone, статусов и ключей без бизнес-агрегации |
| `intermediate` | `int_order_line_revenue`, `int_user_lifecycle`, `int_subscription_periods`, `int_support_by_user_day` | Переиспользуемые join/aggregation steps с явным grain |
| `marts` | `dim_users`, `fct_order_revenue_daily`, `fct_subscription_history`, `mart_customer_revenue_health` | Потребительские таблицы для анализа продукта и финансов |
| `snapshots` | `snap_subscriptions`, `snap_user_plan` | История mutable attributes и SCD type 2 checks |

Профили данных:

- `tiny`: маленький валидный baseline в Git для ручной сверки sources, refs, tests,
  incremental update, snapshot history и final mart;
- `sample`: детерминированная локальная генерация для source freshness, incremental
  windows, SQLFluff performance sanity и docs artifacts;
- дефектные fixtures как минимальные мутации baseline, чтобы каждый dbt failure mode
  проверялся одним тестом.

Заложенные свойства и failure modes:

- модель напрямую читает raw table вместо `source()` и выпадает из lineage;
- `ref()` заменен hardcoded relation name, из-за чего нарушается порядок запуска;
- staging модель меняет grain и размножает пользователей до событий;
- many-to-many join между orders и events размножает revenue;
- source freshness stale, но витрина пересобирается без warning;
- generic tests проходят, но paid revenue не сходится с order items;
- accepted values не обновлены после появления нового subscription status;
- ephemeral model используется там, где compiled SQL становится нечитаемым и тяжелым;
- incremental filter пропускает late-arriving orders или дублирует день без `unique_key`;
- `unique_key` содержит NULL и создает повторные строки при merge/delete+insert strategy;
- `--full-refresh` меняет историческую логику без явного backfill playbook;
- snapshot отслеживает шумную колонку и создает лишние SCD versions;
- macro скрывает бизнес-правило, а compiled SQL перестает проходить code review;
- SQLFluff lint смотрит на generated `target/` или не умеет корректно отрендерить dbt SQL;
- docs сгенерированы, но model/column descriptions и owners не покрывают финальную витрину;
- downstream exposure заявляет потребителя, но не связан с mart model и freshness/test status.

## Контракт аналитической витрины

Каждая публикуемая модель получает machine-readable contract:

```text
model_id
layer
owner
business_question
grain
primary_key
source_tables
upstream_models
materialization
freshness_sla
event_time_column
incremental_strategy
unique_key
late_arrival_window
full_refresh_policy
schema_change_policy
required_tests
warning_checks
accepted_values
reconciliation_rules
snapshot_strategy
documentation_required
downstream_exposures
known_limitations
```

Контракт нужен не для украшения YAML. Он запрещает скрытый переход от «SQL вернул строки»
к «витрина готова для решения». Если grain, owner, tests, freshness или limitations не
объявлены, модель не может считаться опубликованным mart.

## Интеграционный мини-проект

`11/11` собирает поставку:

```text
analytics-mart-dbt/
├── dbt_project.yml
├── profiles.yml.example
├── seeds/
│   └── calendar.csv
├── models/
│   ├── sources.yml
│   ├── staging/
│   │   ├── stg_users.sql
│   │   ├── stg_orders.sql
│   │   └── staging.yml
│   ├── intermediate/
│   │   ├── int_order_line_revenue.sql
│   │   ├── int_user_lifecycle.sql
│   │   └── intermediate.yml
│   └── marts/
│       ├── mart_customer_revenue_health.sql
│       ├── fct_order_revenue_daily.sql
│       └── marts.yml
├── snapshots/
│   └── snap_subscriptions.sql
├── macros/
│   ├── safe_divide.sql
│   └── normalize_money.sql
├── tests/
│   ├── assert_paid_revenue_reconciles.sql
│   └── assert_no_many_to_many_revenue_join.sql
├── docs/
│   └── mart_contract.md
├── target-artifacts/
│   ├── manifest.json
│   ├── catalog.json
│   ├── run_results.json
│   └── lineage-summary.json
├── quality/
│   ├── dbt-test-report.json
│   ├── source-freshness.json
│   ├── sqlfluff-report.json
│   └── contract-audit.json
├── report.md
└── manifest.json
```

Проект обязан:

- запускаться локально через `uv run --locked dbt ...` без внешнего warehouse;
- объявить raw tables только как dbt sources и запретить direct raw references;
- построить staging, intermediate и mart layers с явным grain в properties files;
- использовать `ref()` для всех межмодельных зависимостей;
- выбрать materialization для каждой модели и объяснить trade-off;
- проверять keys, relationships, accepted values, freshness и revenue reconciliation;
- отделить contract gates от warning diagnostics;
- показать compiled SQL для моделей с Jinja и подтвердить читаемость macro output;
- собрать incremental model с late-arrival window, `unique_key` и full-refresh policy;
- собрать snapshot mutable subscription/user-plan attributes с валидными windows;
- сгенерировать docs artifacts и lineage summary из dbt manifest/catalog;
- настроить SQLFluff так, чтобы lint покрывал source models, но не generated `target/`;
- связать каждый claim в `report.md` с model id, test id, freshness check или docs node;
- выпустить SHA-256 manifest всех переданных файлов и версий инструментов.

## Проверяемость

- Tiny-profile содержит ручные ожидаемые ответы для source row counts, staging grain,
  revenue reconciliation, incremental update и snapshot windows.
- `dbt parse`/`compile` tests проверяют, что graph строится через `source()`/`ref()`, а
  hardcoded raw relation считается failure.
- Model tests проверяют materialization, primary keys, relationships и accepted values
  через dbt artifacts, а бизнес-reconciliation - отдельными singular tests.
- Incremental tests запускают full-refresh, затем второй run с late-arriving rows и
  проверяют, что не появились пропущенные или duplicated keys.
- Snapshot tests проверяют SCD validity windows, non-overlap, stable unique key и
  отсутствие версий от шумных колонок.
- Macro tests сравнивают macro input с compiled SQL и блокируют macro, который меняет
  бизнес-смысл без явного contract update.
- SQLFluff tests фиксируют dialect/templater/profile и проверяют, что `target/`,
  `dbt_packages/` и generated artifacts исключены.
- Documentation tests проверяют descriptions для mart models/columns, owners, exposures
  и наличие manifest/catalog/run_results в final package.
- Final package test проверяет структуру `analytics-mart-dbt/`, ссылки claims на dbt
  node ids, согласованность `report.md` с test/freshness status и checksum manifest.
