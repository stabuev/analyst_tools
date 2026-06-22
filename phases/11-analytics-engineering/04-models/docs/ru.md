# Модели и materializations

> Materialization - это не настройка скорости, а договор о том, где живет результат
> модели, кто его читает и какую цену платит следующий запуск.

**Тип:** Build  
**Треки:** Data  
**Пререквизиты:** 11/03 - Sources, refs и зависимости  
**Время:** ~90 минут  
**Результат:** строит staging, intermediate и mart модели, выбирает
view/table/ephemeral materialization по grain, стоимости и потребителю и сверяет compiled
SQL с ожидаемой логикой.

## Цели обучения

- Разложить customer revenue mart на staging, intermediate и mart модели.
- Выбрать `view`, `table` и `ephemeral` по роли модели, а не по привычке.
- Объявить materialization policy в `properties.yml` вместе с grain, consumer и reason.
- Запустить `dbt compile` и увидеть, как ephemeral-модели встраиваются в compiled SQL.
- Проверить физические relations в DuckDB и сверить mart с независимым контролем.

## Проблема

После `11/03` graph уже строится через `source()` и `ref()`, но модели все еще выглядят
как демонстрационный скелет. Теперь нужно собрать настоящую витрину
`mart_customer_revenue_health`: пользователи, заказы, строки заказов, возвраты,
подписки, обращения в поддержку и курсы валют.

Опасность не в том, что SQL не выполнится. Опасность в другом:

- staging можно случайно сделать table и начать хранить вторую копию raw;
- тяжелую финальную витрину можно оставить view, и каждый dashboard будет заново
  исполнять все JOIN и aggregation;
- reusable CTE можно сделать ephemeral, а потом переиспользовать в пяти местах и получить
  нечитаемый compiled SQL;
- materialization можно выбрать устно, но не оставить машинного следа для ревью.

В этом уроке модель считается готовой только если dbt построил проект, manifest подтвердил
materializations, DuckDB показал ожидаемые physical relations, а customer mart сошелся с
независимой ручной сверкой.

## Концепция

### View

`view` хранит SQL, а не результат. На каждом обращении warehouse выполняет underlying
query. Это хороший старт для source-shaped staging: casts, renames, нормализация case,
типизация timestamp, но без бизнес-агрегации.

В уроке все staging-модели - views:

```text
stg_users
stg_events
stg_orders
stg_order_items
stg_subscriptions
stg_support_tickets
stg_refunds
stg_currency_rates
```

### Table

`table` сохраняет результат на момент `dbt run`. Читать ее быстрее и стабильнее, но новые
raw rows не появятся в ней сами: нужен следующий запуск. Это нормально для
consumer-facing mart, если внешний scheduler пересобирает проект по понятному графику.

В уроке table одна:

```text
mart_customer_revenue_health
```

### Ephemeral

`ephemeral` не создает таблицу или view. dbt встраивает SQL такой модели в downstream
модель как CTE с именем вида `__dbt__cte__...`.

В уроке ephemeral только легкие промежуточные шаги с ограниченным fanout:

```text
int_order_line_revenue
int_refunds_by_order
```

Их удобно переиспользовать внутри mart, но их не нужно запрашивать напрямую как отдельные
relations.

### Materialization policy

Выбор хранится в `outputs/materialization_project/models/properties.yml`:

```yaml
models:
  - name: mart_customer_revenue_health
    config:
      materialized: table
    meta:
      layer: marts
      grain: "one active non-deleted user"
      consumer: "product and finance analysis"
      materialization_reason: "Published mart is queried by consumers..."
      cost_note: "Rebuild cost is acceptable..."
```

`config.materialized` говорит dbt, что делать. `meta` говорит ревьюеру, почему это
решение допустимо.

## Соберите это

### Шаг 1: откройте структуру проекта

Файл:

```text
outputs/materialization_project/dbt_project.yml
```

задает стандартные директории и folder defaults:

```yaml
models:
  materialization_project:
    staging:
      +materialized: view
    intermediate:
      +materialized: view
    marts:
      +materialized: table
```

Это default, а не окончательное решение. Точная политика находится в `properties.yml` для
каждой модели.

### Шаг 2: прочитайте staging models

Staging читает raw только через `source()`:

```sql
select
    order_id,
    user_id,
    cast(ordered_at as timestamptz) as ordered_at,
    cast(cast(ordered_at as timestamptz) as date) as order_date,
    lower(status) as status,
    upper(currency) as currency,
    cast(amount as decimal(18, 2)) as amount
from {{ source('raw_app', 'orders') }}
```

Здесь есть типизация и нормализация, но нет join к order items и нет consumer metric.

### Шаг 3: прочитайте intermediate models

`int_order_line_revenue` - line-level reusable step:

```sql
from {{ ref('stg_order_items') }} as items
inner join {{ ref('stg_orders') }} as orders
```

`int_support_by_user` и `int_subscription_latest` оставлены views, потому что их полезно
запрашивать отдельно при диагностике.

### Шаг 4: прочитайте mart

`mart_customer_revenue_health` объединяет:

```text
stg_users
stg_currency_rates
int_order_line_revenue
int_refunds_by_order
int_support_by_user
int_subscription_latest
```

Grain витрины - один активный неудаленный пользователь. Денежная нормализация переводит
USD-заказ в RUB через `stg_currency_rates`, а refund не попадает в `paid_revenue_rub`.

### Шаг 5: запустите аудитор

Из корня урока:

```bash
python outputs/materialization_reporter.py \
  --project outputs/materialization_project \
  --data-contract ../data/contract.json \
  --output outputs/materialization_report.json \
  --run-dbt
```

Аудитор создает временную DuckDB-базу, загружает `../data/tiny/*.csv` в schema `raw`,
запускает `dbt parse`, `dbt compile --select mart_customer_revenue_health`, `dbt run`,
читает `target/manifest.json` и проверяет physical relations.

## Используйте это

Запустите компактный пример:

```bash
python code/main.py
```

Ожидаемый смысл отчета:

```json
{
  "valid": true,
  "materializations": {
    "ephemeral": 2,
    "table": 1,
    "view": 10
  },
  "physical_relations": {
    "table": 1,
    "view": 10
  },
  "mart_rows": 5
}
```

Обратите внимание: моделей 13, а физических relations 11. Две ephemeral-модели не
создаются в DuckDB. Они встраиваются в compiled SQL mart-модели.

## Сломайте это

### Сделайте staging table

В `properties.yml` замените для `stg_orders`:

```yaml
materialized: table
```

Аудитор должен провалить `materializations_match_policy`. Staging table может быть
оправдана в реальном проекте, но тогда нужно изменить policy и объяснить цену хранения
копии raw-shaped данных.

### Уберите reason

Удалите `meta.materialization_reason` у mart. SQL все еще может собраться, но ревьюер
потеряет rationale. Аудитор провалит `materialization_decisions_documented`.

### Расширьте fanout ephemeral

Если `int_order_line_revenue` начнут читать несколько downstream-моделей, compiled SQL
начнет дублировать сложный CTE. В таком случае модель лучше сделать view или table.
Аудитор ловит это через `ephemeral_models_have_limited_fanout`.

### Удалите курс валюты USD

Если убрать строку USD из `raw_currency_rates.csv`, dbt run пройдет: left join не
является синтаксической ошибкой. Но `mart_matches_independent_control` провалится, потому
что пользователь `u005` потеряет выручку в RUB.

## Проверьте это

Локальная проверка урока:

```bash
python -m unittest discover -s tests -v
```

Тесты покрывают:

- корректную materialization policy;
- запрет `incremental` и `materialized_view` до следующих уроков;
- обязательный reason/consumer/grain в `meta`;
- сохранение `source()` только в staging;
- сохранение `ref()` в downstream-моделях;
- ограниченный fanout ephemeral-моделей;
- live `dbt parse/compile/run`;
- physical relation count в DuckDB;
- независимую сверку 5 строк customer mart.

## Поставьте результат

Артефакт урока:

```text
outputs/materialization_reporter.py
```

Он применим к учебному dbt-проекту:

```bash
python outputs/materialization_reporter.py \
  --project outputs/materialization_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Статический committed report:

```text
outputs/materialization_report.json
```

Он фиксирует ожидаемые 13 моделей и materialization policy без временных путей и
timestamp.

## Упражнения

1. Сделайте `int_support_by_user` ephemeral и объясните, почему это ухудшает
   inspectability для support-диагностики.
2. Добавьте в mart поле `net_revenue_rub = paid_revenue_rub - refunded_amount_rub` и
   расширьте independent control.
3. Сделайте `mart_customer_revenue_health` view, запустите аудитор и сформулируйте,
   при каком реальном профиле данных это могло бы быть допустимо.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Materialization | "Опция производительности" | Стратегия сохранения или встраивания результата dbt-модели |
| View | "Всегда дешевле table" | Не хранит результат, но может дорого выполняться при каждом чтении |
| Table | "Всегда правильный выбор для надежности" | Хранит результат `dbt run`, но требует пересборки для новых данных |
| Ephemeral | "Бесплатная переиспользуемая модель" | Встраивается как CTE и может раздувать compiled SQL |
| Compiled SQL | "Внутренняя техническая деталь" | SQL, который реально исполняет warehouse и который нужно уметь ревьюить |

## Дополнительное чтение

- [dbt: Materializations](https://docs.getdbt.com/docs/build/materializations) - разберите официальные trade-offs `view`, `table`, `incremental`, `ephemeral` и `materialized_view`; особенно ограничения ephemeral.
- [dbt: About dbt compile command](https://docs.getdbt.com/reference/commands/compile) - посмотрите, где dbt хранит compiled SQL и почему его полезно читать при ревью сложных моделей.
- [dbt: Manifest JSON file](https://docs.getdbt.com/reference/artifacts/manifest-json) - изучите, какие node configs и properties попадают в `target/manifest.json`, и почему аудитор может проверять graph машинно.
- [dbt: Model configs](https://docs.getdbt.com/reference/model-configs) - прочитайте, где можно задавать config: в project file, properties file или прямо в SQL-модели.
