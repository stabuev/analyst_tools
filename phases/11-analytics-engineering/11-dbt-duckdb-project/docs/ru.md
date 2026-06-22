# Локальный проект с dbt-duckdb

> Финальный dbt-проект готов не тогда, когда `dbt run` зеленый, а когда пакет можно воспроизвести, проверить, объяснить и безопасно передать другому человеку.

**Тип:** Case  
**Треки:** Data  
**Пререквизиты:** 11-analytics-engineering/10-sqlfluff  
**Время:** ~120 минут  
**Результат:** собираете локальный `analytics-mart-dbt` package для customer revenue health mart: sources, staging/intermediate/mart models, tests, macros, incremental model, snapshot, docs, lineage, SQLFluff report, dbt artifacts и checksum manifest.

## Цели обучения

- Собрать переносимый dbt-duckdb проект без внешнего warehouse.
- Провести raw boundary через `source()` и downstream dependencies через `ref()`.
- Объяснить materialization choices для staging, intermediate, mart, incremental и snapshot слоев.
- Разделить blocking contract gates и warning diagnostics.
- Сгенерировать `manifest.json`, `catalog.json`, `run_results.json` и компактный lineage summary.
- Проверить SQLFluff, source freshness, report traceability и SHA-256 checksums.
- Поставить пакет как воспроизводимый handoff artifact.

## Проблема

За фазу 11 вы построили все важные части analytics engineering проекта:

- слои данных и raw contract;
- dbt project, sources и refs;
- staging, intermediate и mart models;
- generic и singular data tests;
- macros;
- incremental model;
- snapshot;
- documentation, exposure и lineage;
- SQLFluff style gate.

Но в реальной работе эти части недостаточно просто иметь в разных папках. Потребителю нужен
готовый пакет:

```text
Можно ли запустить проект локально?
Какие raw sources входят в контракт?
Какие модели и тесты защищают dashboard claims?
Что было собрано в последнем release?
Нет ли style violations?
Не изменился ли файл после проверки?
```

Если на эти вопросы нет машинно-проверяемого ответа, проект остается учебной заготовкой.
Финальный урок превращает его в release package.

## Концепция

Выпускной пакет состоит из трех поверхностей.

| Поверхность | Что хранит | Зачем нужна |
|---|---|---|
| Source project | `dbt_project.yml`, `profiles.yml`, `models/`, `macros/`, `tests/`, `snapshots/`, `seeds/` | То, что аналитик редактирует и ревьюит |
| Build evidence | `target-artifacts/`, `quality/`, `report.md` | Доказательство, что проект был собран и проверен |
| Release integrity | `manifest.json` с SHA-256 | Защита от незаметных изменений после проверки |

Главная идея: dbt artifacts и отчеты качества не заменяют исходники. Они фиксируют состояние
исходников в момент выпуска.

### Raw boundary

Raw-таблицы объявлены только в `models/sources.yml`:

```sql
select * from {{ source('raw_app', 'orders') }}
```

После staging-слоя проект должен использовать `ref()`:

```sql
select * from {{ ref('stg_orders') }}
```

Прямая ссылка вроде `raw.raw_orders` внутри модели является release blocker. Иначе вы
обходите freshness, owner, descriptions, source lineage и staging normalization.

### Materialization contract

В проекте есть несколько materialization choices:

| Слой | Materialization | Причина |
|---|---|---|
| Staging | `view` | легкая нормализация raw columns, всегда свежая проекция |
| Intermediate | `view` или `ephemeral` | переиспользуемая логика без consumer contract |
| Mart | `table` | стабильная потребительская поверхность |
| Daily revenue fact | `incremental` | растущий факт с late-arrival window |
| Subscription history | `snapshot` + view | point-in-time история mutable source |

У `fct_order_revenue_daily` контракт явно фиксирует:

- `unique_key = revenue_date`;
- `incremental_strategy = delete+insert`;
- окно late-arriving rows: 2 дня;
- `on_schema_change = fail`;
- full-refresh policy для изменения grain, ключа или currency logic.

### Quality gates

Не все проверки одинаковые.

Blocking gates:

```text
assert_paid_revenue_reconciles
assert_daily_revenue_reconciles
assert_no_many_to_many_revenue_join
assert_subscription_history_has_one_current_row
assert_subscription_history_windows_do_not_overlap
assert_snapshot_does_not_version_noisy_updated_at
```

Warning diagnostic:

```text
warn_customers_without_subscription
```

Warning остается в `quality/dbt-test-report.json`, но не блокирует пакет. Это не слабость:
так команда видит риск, не ломая release там, где риск является ожидаемой диагностикой.

## Соберите это

Откройте структуру артефакта:

```text
outputs/analytics-mart-dbt/
  dbt_project.yml
  profiles.yml
  models/
  macros/
  snapshots/
  tests/
  seeds/calendar.csv
  docs/mart_contract.md
  target-artifacts/
  quality/
  report.md
  manifest.json
```

Пакет собирает и проверяет `analytics_mart_packager.py`.

```bash
uv run --locked python phases/11-analytics-engineering/11-dbt-duckdb-project/outputs/analytics_mart_packager.py \
  --build-package \
  --output phases/11-analytics-engineering/11-dbt-duckdb-project/outputs/package_audit.json
```

Packager делает временную копию проекта, загружает CSV fixtures в DuckDB и запускает:

```bash
dbt parse
dbt run --exclude int_subscription_history
dbt snapshot --select subscription_status_snapshot
dbt run --select int_subscription_history
dbt test --select test_type:data
dbt docs generate
python -m sqlfluff lint models tests snapshots --format json
```

Порядок важен. `int_subscription_history` зависит от snapshot relation, поэтому сначала
собираются обычные модели, затем snapshot, затем history view.

## Используйте это

Быстрый пример не пересобирает dbt, а валидирует готовый пакет:

```bash
uv run --locked python phases/11-analytics-engineering/11-dbt-duckdb-project/code/main.py
```

Ожидаемая форма ответа:

```json
{
  "package": "analytics-mart-dbt",
  "valid": true,
  "release_files": 10,
  "checksum_files": 50,
  "dbt_tests": {
    "status": "pass",
    "count": 87,
    "warnings": 1
  },
  "sqlfluff": {
    "status": "pass",
    "files": 22,
    "violations": 0
  }
}
```

Главные файлы handoff:

```text
outputs/analytics-mart-dbt/target-artifacts/manifest.json
outputs/analytics-mart-dbt/target-artifacts/catalog.json
outputs/analytics-mart-dbt/target-artifacts/run_results.json
outputs/analytics-mart-dbt/target-artifacts/lineage-summary.json
outputs/analytics-mart-dbt/quality/dbt-test-report.json
outputs/analytics-mart-dbt/quality/source-freshness.json
outputs/analytics-mart-dbt/quality/sqlfluff-report.json
outputs/analytics-mart-dbt/quality/contract-audit.json
outputs/analytics-mart-dbt/report.md
outputs/analytics-mart-dbt/manifest.json
```

`report.md` связывает бизнес-claims с dbt node ids:

```text
customer_health_segment_supported
  model.analytics_mart_dbt.mart_customer_revenue_health
  test.analytics_mart_dbt.assert_paid_revenue_reconciles
  test.analytics_mart_dbt.warn_customers_without_subscription
```

Это важно: отчет должен ссылаться на реальные узлы graph, а не просто говорить «витрина
проверена».

## Сломайте это

1. В `models/staging/stg_orders.sql` замените `source('raw_app', 'orders')` на
   `raw.raw_orders`. Аудитор должен упасть на raw boundary.
2. В `models/marts/fct_order_revenue_daily.sql` замените `interval '2 days'` на
   `interval '10 days'`. Аудитор должен упасть на incremental contract.
3. В `.sqlfluff` замените `templater = dbt` на `templater = jinja`. Аудитор должен
   упасть на SQLFluff/dbt templater contract.
4. В `report.md` переименуйте один `test.analytics_mart_dbt...` node id. Release validation
   должен упасть на traceability.
5. После успешного build допишите строку в `docs/mart_contract.md`. Checksum validation
   должен упасть, даже если dbt artifacts еще лежат на месте.

Эти поломки проверяют разные уровни: source contract, model behavior, style config,
consumer report и release integrity.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/11-analytics-engineering/11-dbt-duckdb-project/tests
```

Тесты проверяют:

- готовый пакет содержит все release files;
- live build на временной копии заново создает dbt artifacts и quality reports;
- direct raw references запрещены;
- incremental fact обязан иметь late-arrival window;
- SQLFluff должен использовать DuckDB dialect и dbt templater;
- `report.md` claims обязаны резолвиться в manifest nodes;
- checksum manifest ловит любые изменения после release;
- CLI пишет JSON report и возвращает non-zero для сломанного проекта.

Для проверки всего курса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Итоговый артефакт:

```text
outputs/analytics-mart-dbt
```

Минимальный handoff checklist:

```text
[x] dbt parse/run/snapshot/test/docs generate passed
[x] SQLFluff lint passed on models/tests/snapshots
[x] 87 dbt data tests recorded, warning diagnostics visible
[x] source freshness report covers 8 raw sources
[x] exposure lineage resolves to mart/fact/history models
[x] report.md claims resolve to manifest node ids
[x] manifest.json SHA-256 checksums match release files
```

Если вы переносите этот пакет в другой проект, меняйте не только SQL. Обновите:

- `EXPECTED_PROJECT_NAME` в packager-е;
- `profiles.yml` и `.sqlfluff`;
- список expected models/tests/claims;
- source contract;
- release report генератор;
- checksum manifest через новый build.

## Упражнения

1. Добавьте новый singular test для `mart_customer_revenue_health` и расширьте
   `EXPECTED_BLOCKING_TESTS`, чтобы release требовал этот тест.
2. Добавьте второй exposure для finance notebook и проверьте, что lineage summary показывает
   оба downstream consumer-а.
3. Сделайте отдельный `quality/macro-compile-review.json`, который хранит compiled SQL для
   моделей с macros `to_decimal()` и `rub_amount()`.
4. Добавьте seed `calendar.csv` в одну из моделей и расширьте checksum/report так, чтобы seed
   был виден как зависимость.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Release package | «Это просто zip с проектом» | Исходники + build evidence + проверка целостности |
| Raw boundary | «Можно обращаться к raw где удобно» | Единственная точка входа через documented dbt sources |
| Build evidence | «Логи запуска» | Машинно-читаемые артефакты dbt, quality reports и lineage summary |
| Warning diagnostic | «Почти ошибка» | Видимый риск, который не блокирует release по договору команды |
| Checksum manifest | «Формальность» | Способ доказать, что проверенные файлы не менялись после release |
| Traceable report | «Красивый Markdown» | Отчет, claims которого ссылаются на реальные dbt node ids |

## Дополнительное чтение

- [dbt_project.yml](https://docs.getdbt.com/reference/dbt_project.yml) — какие пути, профили и resource configs делают папку настоящим dbt-проектом.
- [dbt Sources](https://docs.getdbt.com/docs/build/sources) — как объявлять raw sources, freshness и source-level tests.
- [dbt `ref()`](https://docs.getdbt.com/reference/dbt-jinja-functions/ref) — почему dependencies должны идти через graph, а не через hardcoded relation names.
- [dbt Incremental Models](https://docs.getdbt.com/docs/build/incremental-models) — как проектировать incremental filters, unique keys и full-refresh сценарии.
- [dbt Artifacts: manifest.json](https://docs.getdbt.com/reference/artifacts/manifest-json) — какие части graph, ресурсов и compiled metadata попадают в release evidence.
