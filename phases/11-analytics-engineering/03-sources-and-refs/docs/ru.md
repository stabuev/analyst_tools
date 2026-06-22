# Sources, refs и зависимости

> Lineage появляется не от красивой диаграммы, а от того, что raw читается через
> `source()`, а модели друг друга - через `ref()`.

**Тип:** Build  
**Треки:** Data  
**Пререквизиты:** 11/02 - Структура dbt-проекта  
**Время:** ~75 минут  
**Результат:** объявляет raw tables как sources, строит model dependencies через
`source()` и `ref()`, проверяет source freshness и запрещает скрытые прямые обращения к
raw-таблицам.

## Цели обучения

- Объявить все raw tables фазы как dbt sources с `identifier` и `loaded_at_field`.
- Построить staging models, которые читают raw только через `source()`.
- Построить intermediate и mart models, которые читают upstream models только через
  `ref()`.
- Проверить manifest dependencies: sources видны как source nodes, downstream models не
  прыгают напрямую в raw.
- Запустить `dbt source freshness` в локальном DuckDB-проекте и сохранить machine-readable
  audit.

## Проблема

После `11/02` у нас есть рабочий dbt skeleton, но smoke graph не знает настоящих данных.
Теперь команда добавляет raw extract:

```text
raw_users
raw_orders
raw_order_items
raw_events
raw_subscriptions
raw_support_tickets
raw_refunds
raw_currency_rates
```

Быстрый способ - написать в модели:

```sql
select *
from raw.raw_orders
```

Он соблазнительный, потому что сразу работает в DuckDB. Но dbt тогда не знает, что модель
зависит от source. Документация, source freshness, selectors, downstream lineage и ревью
графа становятся неполными. Ошибка не синтаксическая, а инженерная: SQL вернул строки, но
контракт источника исчез.

## Концепция

### Source - именованная raw boundary

В `models/sources.yml` raw table получает dbt-имя:

```yaml
sources:
  - name: raw_app
    schema: raw
    tables:
      - name: orders
        identifier: raw_orders
```

В SQL модель читает:

```sql
from {{ source('raw_app', 'orders') }}
```

dbt компилирует это в relation для текущего target и добавляет source dependency в
manifest.

### `identifier` отделяет удобное имя от физической таблицы

Физическая таблица может называться `raw_order_items`, а в dbt source ее удобнее читать
как `order_items`:

```yaml
- name: order_items
  identifier: raw_order_items
```

Так source name остается стабильным для аналитика, а физический raw naming не протекает в
каждый SQL-файл.

### Freshness - SLA источника, а не тест mart

`dbt source freshness` смотрит на timestamp загрузки:

```yaml
config:
  loaded_at_field: updated_at
  freshness:
    warn_after: {count: 10000, period: day}
    error_after: {count: 20000, period: day}
```

В продакшене пороги должны отражать настоящий SLA. В уроке окно большое, чтобы tiny
fixture оставался воспроизводимым независимо от даты запуска курса.

### `ref()` связывает модели внутри graph

Intermediate модель читает staging так:

```sql
from {{ ref('stg_order_items') }} as items
join {{ ref('stg_orders') }} as orders
```

Mart читает intermediate/staging так:

```sql
from {{ ref('stg_users') }} as users
left join {{ ref('int_order_line_revenue') }} as revenue
```

Это дает dbt порядок сборки: сначала sources и staging, затем intermediate, затем mart.

## Соберите это

### Шаг 1: соберите ручную карту зависимостей

До dbt можно описать graph как список ребер:

```text
raw_app.orders -> stg_orders
raw_app.order_items -> stg_order_items
stg_orders -> int_order_line_revenue
stg_order_items -> int_order_line_revenue
stg_users -> mart_customer_revenue_health
int_order_line_revenue -> mart_customer_revenue_health
```

Это минимальный механизм: если модель читает raw напрямую, ребро должно быть видно.

### Шаг 2: откройте dbt source declaration

Файл:

```text
outputs/source_ref_project/models/sources.yml
```

объявляет все восемь raw tables из `../data/contract.json`. У каждой таблицы есть:

```text
name
identifier
loaded_at_field
freshness.warn_after
freshness.error_after
```

`identifier` должен совпадать с физическим raw table из data contract, а
`loaded_at_field` - с `freshness_column`.

### Шаг 3: прочитайте staging SQL

Файлы:

```text
models/staging/stg_users.sql
models/staging/stg_orders.sql
models/staging/stg_order_items.sql
```

читают raw только через `source()`. В этих моделях нормализуются имена, типы, case и
timestamp, но не строится mart.

### Шаг 4: прочитайте `ref()` graph

Файлы:

```text
models/intermediate/int_order_line_revenue.sql
models/marts/mart_customer_revenue_health.sql
```

не читают raw. Они используют только `ref()`, чтобы зависеть от уже объявленных моделей.

### Шаг 5: запустите аудитор

Из корня урока:

```bash
python outputs/source_ref_lineage_auditor.py \
  --project outputs/source_ref_project \
  --data-contract ../data/contract.json \
  --output outputs/source_ref_lineage_audit.json \
  --run-dbt
```

Аудитор создает временную DuckDB-базу, загружает `../data/tiny/*.csv` в schema `raw`,
запускает `dbt parse`, `dbt compile`, `dbt source freshness` и проверяет manifest.

## Используйте это

В рабочем dbt-проекте вы будете часто смотреть не только SQL, но и artifacts:

```text
target/manifest.json
target/sources.json
```

`manifest.json` показывает, какие source/model nodes реально попали в graph. Если в SQL
есть `raw.raw_orders`, но нет `source.raw_app.orders` в dependencies, lineage сломан.

`sources.json` показывает результат freshness check. В этом уроке все 8 sources получают
status `pass`, потому что tiny fixture фиксированный, а freshness window учебно широкий.

Проверьте compact summary:

```bash
python code/main.py
```

## Сломайте это

### Staging читает raw напрямую

Плохой вариант:

```sql
select *
from raw.raw_orders
```

Аудитор должен провалить:

```text
source_calls_stay_in_staging
sql_has_no_direct_raw_references
```

### Mart читает source напрямую

Плохой вариант:

```sql
select user_id
from {{ source('raw_app', 'users') }}
```

Технически dbt может это скомпилировать. Архитектурно mart обходит staging boundary, и
manifest покажет source dependency там, где должен быть model dependency.

### `ref()` заменен hardcoded relation

Плохой вариант:

```sql
select *
from analytics.stg_orders
```

Такой SQL зависит от конкретной schema и не создает dbt dependency. При переезде target,
изменении materialization или выборочном запуске порядок сборки станет неявным.

### Freshness column расходится с contract

Если для `orders` указать:

```yaml
loaded_at_field: loaded_at
```

а data contract говорит `updated_at`, freshness check уже не проверяет ту границу, которую
согласовала команда.

## Проверьте это

Behavioral tests проверяют:

- valid project объявляет 8 raw sources из data contract;
- source identifiers совпадают с `raw_*` таблицами;
- `loaded_at_field` совпадает с `freshness_column`;
- у каждой source table есть `warn_after` и `error_after`;
- staging models читают через `source()`;
- downstream models не читают source напрямую;
- intermediate/mart models используют `ref()`;
- SQL не содержит hardcoded `raw_*` identifiers;
- live dbt run создает manifest с source/model dependencies;
- source freshness возвращает 8 pass statuses.

Запуск:

```bash
python -m unittest discover -s tests
```

## Поставьте результат

Итоговый артефакт:

```text
outputs/source_ref_lineage_auditor.py
```

Он работает отдельно от текста урока:

```bash
python outputs/source_ref_lineage_auditor.py \
  --project outputs/source_ref_project \
  --data-contract ../data/contract.json \
  --output outputs/source_ref_lineage_audit.json \
  --run-dbt
```

Передайте вместе с ним:

```text
outputs/source_ref_project/
outputs/source_ref_lineage_audit.json
```

Следующий урок будет расширять этот graph настоящими model materializations и compiled SQL
review.

## Упражнения

1. Добавьте staging-модель `stg_subscriptions.sql`, которая читает
   `{{ source('raw_app', 'subscriptions') }}` и не меняет grain.
2. Сделайте `mart_customer_revenue_health.sql` зависящим напрямую от `source('raw_app',
   'orders')`, запустите аудитор и объясните, почему ошибка не сводится к SQL syntax.
3. Уменьшите freshness window для `events` до одного дня и посмотрите, как изменится
   `target/sources.json` в live-прогоне.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Source | Просто alias для таблицы | Именованная raw boundary, которая попадает в dbt manifest, docs, selectors и freshness |
| `identifier` | Новое физическое имя таблицы | Связь удобного dbt source name с реальным warehouse table name |
| `source()` | Сокращение для `schema.table` | Jinja-функция, которая возвращает relation и создает source dependency |
| `ref()` | Текстовая подстановка имени файла | Jinja-функция, которая возвращает relation и создает model dependency |
| Source freshness | Проверка всех значений в таблице | SLA-проверка максимального loaded timestamp source table |
| Direct raw reference | Нормальная оптимизация SQL | Скрытый обход dbt lineage, staging boundary и source freshness contract |

## Дополнительное чтение

- [dbt: Add sources to your DAG](https://docs.getdbt.com/docs/build/sources) — разберите declaration, `identifier`, source tests, source freshness и selectors для downstream models.
- [dbt: About source function](https://docs.getdbt.com/reference/dbt-jinja-functions/source) — посмотрите точные аргументы `source_name` и `table_name`, которые используются в staging SQL урока.
- [dbt: About ref function](https://docs.getdbt.com/reference/dbt-jinja-functions/ref) — свяжите `ref()` с Relation object, dependency graph и порядком запуска моделей.
- [dbt: About dbt source command](https://docs.getdbt.com/reference/commands/source) — изучите формат `dbt source freshness`, exit codes и artifact `target/sources.json`.
- [dbt: Node selection syntax](https://docs.getdbt.com/reference/node-selection/syntax) — примените source selectors вроде `source:raw_app.orders+` к graph из этого урока.
