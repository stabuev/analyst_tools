# Документация и lineage

> Витрина становится продуктом только тогда, когда потребитель видит не только таблицу, но и владельца, grain, проверки, lineage и downstream-риски.

**Тип:** Learn
**Треки:** Data
**Пререквизиты:** 11-analytics-engineering/08-snapshots
**Время:** ~75 минут
**Результат:** публикуете описания sources, models, columns, tests и exposures, генерируете dbt docs artifacts и связываете downstream claims с lineage и owners.

## Цели обучения

- Отличить "описали таблицу" от проверяемого documentation contract.
- Документировать sources, models, columns, snapshots и singular data tests.
- Описать downstream dashboard через dbt exposure с owner, maturity и `depends_on`.
- Сгенерировать `manifest.json` и `catalog.json` через `dbt docs generate`.
- Проверить, что dashboard claims связаны с upstream-моделями, тестами и владельцами.

## Проблема

После `11/08` у нас есть рабочий dbt-граф: raw sources, staging, intermediate, mart, incremental fact, snapshot и data tests. Но для потребителя dashboard этого мало.

Плохой handoff выглядит так:

```text
Возьми mart_customer_revenue_health, там все посчитано.
```

Коллега сразу спросит:

- одна строка - это пользователь, заказ или подписка;
- кто владелец витрины;
- какие источники и freshness policy стоят выше;
- какие тесты защищают revenue и SCD history;
- можно ли построить dashboard claim напрямую из raw source;
- где посмотреть lineage, если число в отчете не сходится.

Документация в dbt нужна не для красоты. Она превращает SQL-граф в договор с потребителем: что означает ресурс, кто за него отвечает, какие проверки проходят и какое downstream-использование зависит от него.

## Концепция

В этом уроке документация состоит из четырех слоев.

| Слой | Что описывает | Какой риск снимает |
|---|---|---|
| Resource docs | Sources, models, snapshots, columns, tests | Потребитель не знает grain, типы и ограничения |
| Owners | `owner`, `owner_email`, exposure owner | Непонятно, кто чинит поломку или отвечает на вопрос |
| Lineage | `ref()`, `source()`, manifest `parent_map`/`child_map` | Невозможно понять путь числа от raw до dashboard |
| Exposures | Dashboard, notebook, ML/application use | Downstream claim не связан с upstream-моделями и тестами |

У dbt есть два важных артефакта:

- `manifest.json` - полное представление ресурсов проекта: models, sources, tests, snapshots, exposures, docs blocks и graph dependencies.
- `catalog.json` - metadata из warehouse: relations, columns, types и table/view information, которые используются в docs site.

`manifest` отвечает на вопрос "что объявлено в проекте и как связано". `catalog` отвечает на вопрос "что реально есть в warehouse после сборки".

## Соберите это

Сначала сделайте documentation contract вручную, без dbt.

### Шаг 1. Назовите consumer claim

Dashboard claim:

```text
Customer health segment is backed by paid revenue, refunds and support load.
```

Для него нужен минимум:

- downstream asset: `customer_revenue_health_dashboard`;
- owner: `Analytics Engineering Team`;
- upstream model: `mart_customer_revenue_health`;
- required tests: `assert_paid_revenue_reconciles`, `warn_customers_without_subscription`;
- grain: one active non-deleted user.

Если claim не связан с моделью и тестами, это уже не documentation contract, а просто текст.

### Шаг 2. Проведите lineage

Минимальная цепочка:

```text
raw_orders + raw_order_items + raw_refunds + raw_currency_rates
  -> stg_orders / stg_order_items / stg_refunds / stg_currency_rates
  -> int_order_line_revenue + int_refunds_by_order
  -> mart_customer_revenue_health
  -> customer_revenue_health_dashboard
```

Для SCD claim цепочка другая:

```text
raw_subscriptions
  -> stg_subscriptions
  -> subscription_status_snapshot
  -> int_subscription_history
  -> customer_revenue_health_dashboard
```

Lineage без claim полезен инженеру, но слаб для бизнеса. Claim без lineage полезен в презентации, но слаб для ревью.

### Шаг 3. Проверьте coverage

Для consumer-facing ресурсов проверяйте:

- model description не пустой;
- все ключевые output columns описаны;
- model `meta` содержит owner, owner email, grain и consumer;
- singular tests имеют descriptions;
- exposure не зависит напрямую от raw source;
- exposure claims называют upstream models и required tests.

## Используйте это

Готовый проект лежит в `outputs/documentation_project`.

В нем добавлены:

- `models/docs.md` - docs blocks для overview, mart, SCD history и dashboard;
- `models/exposures.yml` - exposure `customer_revenue_health_dashboard`;
- descriptions для sources, key columns, mart, daily fact, snapshot и singular tests;
- `outputs/documentation_lineage_auditor.py` - gate, который читает YAML и dbt artifacts.

Запустите из папки `phases/11-analytics-engineering/09-documentation-and-lineage`:

```bash
uv run --locked python outputs/documentation_lineage_auditor.py \
  --project outputs/documentation_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Live-аудит делает:

1. Загружает tiny raw CSV в DuckDB.
2. Запускает `dbt parse`.
3. Строит модели, snapshot и history-модель.
4. Запускает data tests.
5. Выполняет `dbt docs generate`.
6. Проверяет `target/manifest.json` и `target/catalog.json`.

Ключевые live-checks:

```text
dbt_docs_generate_succeeds
docs_generate_writes_manifest_and_catalog
manifest_contains_docs_blocks
manifest_exposure_lineage_resolves
manifest_claim_tests_are_documented
catalog_contains_key_resources_and_columns
```

## Сломайте это

Проверьте пять поломок:

1. Удалите `owner.email` у exposure. Dashboard больше не имеет ответственного.
2. Добавьте в `depends_on` exposure прямой `source('raw_app', 'orders')`. Consumer bypasses documented mart contract.
3. Удалите docs block `mart_customer_revenue_health_docs`. `doc()` больше не сможет дать consumer-facing описание.
4. Уберите описание `paid_revenue_rub`. Claim про revenue останется без объяснения ключевой колонки.
5. Удалите description у `assert_daily_revenue_reconciles`. В manifest будет тест, но потребитель не поймет, какой риск он закрывает.

## Проверьте это

Локальная проверка урока:

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked python code/main.py
```

`code/main.py` выводит compact report:

```json
{
  "checks": "12/12",
  "key_models": [
    "fct_order_revenue_daily",
    "int_subscription_history",
    "mart_customer_revenue_health"
  ],
  "valid": true
}
```

Behavioral tests покрывают:

- валидный documentation contract;
- live `dbt docs generate`;
- missing exposure owner;
- direct raw source dependency in exposure;
- broken decision claim tests;
- missing docs block;
- missing key column docs или owner;
- source freshness mismatch;
- missing singular data test descriptions;
- CLI exit code и JSON report.

## Поставьте результат

Именованный артефакт:

- `outputs/documentation_lineage_auditor.py` - CLI-аудитор документации и lineage.
- `outputs/documentation_lineage_report.json` - deterministic static report.
- `outputs/documentation_project/` - dbt-проект с docs blocks, exposure, documented sources/models/tests/snapshot.

Команда для CI artifact:

```bash
python outputs/documentation_lineage_auditor.py \
  --project outputs/documentation_project \
  --data-contract ../data/contract.json \
  --run-dbt \
  --output outputs/documentation_lineage_report.json
```

Такой gate полезен перед публикацией dbt docs: он не дает выпустить dashboard lineage, где есть красивые описания, но нет owner, tests или machine-readable связи между claim и upstream-моделью.

## Упражнения

1. Добавьте второй exposure типа `notebook` для ad-hoc subscription lifecycle analysis и свяжите его только с `int_subscription_history`.
2. Расширьте `documentation_contract` у `mart_customer_revenue_health`: добавьте claim про support tickets и required test для orphan users.
3. Измените auditor так, чтобы он считал долю documented columns по всем моделям, а не только по consumer-facing ресурсам.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| dbt docs | "HTML-страница поверх SQL" | Documentation system, который использует descriptions, graph metadata, manifest и catalog |
| Manifest | "Файл только для dbt internals" | Machine-readable представление ресурсов проекта и lineage |
| Catalog | "То же самое, что manifest" | Warehouse metadata о построенных relations и колонках |
| Exposure | "Ссылка на dashboard" | Downstream resource с owner, maturity, description и dependencies |
| Docs block | "Длинный комментарий" | Reusable Markdown-блок, подключаемый через `doc()` |
| Owner | "Подпись автора" | Операционный ответственный за ресурс или downstream consumer asset |
| Decision claim | "Текст в dashboard" | Проверяемое утверждение, связанное с upstream models и tests |

## Дополнительное чтение

- [dbt: About documentation](https://docs.getdbt.com/docs/build/documentation) — как descriptions, docs blocks и generated docs превращают dbt-проект в понятный потребителю каталог.
- [dbt: View documentation](https://docs.getdbt.com/docs/build/view-documentation) — чем отличаются dbt Docs, dbt Docs v2 и Catalog, и как lineage показывается в интерфейсе.
- [dbt: Exposures](https://docs.getdbt.com/docs/build/exposures) — как описывать downstream dashboards, notebooks, applications и owners в DAG.
- [dbt: Manifest JSON](https://docs.getdbt.com/reference/artifacts/manifest-json) — какие ресурсы и dependency maps доступны для machine-readable lineage checks.
- [dbt: Catalog JSON](https://docs.getdbt.com/reference/artifacts/catalog-json) — какая warehouse metadata появляется после `dbt docs generate` и зачем сверять catalog с manifest.
