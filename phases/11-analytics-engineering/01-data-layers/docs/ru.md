# Слои и контракты аналитических данных

> Витрина начинается не с SQL, а с договора: какой слой за что отвечает, какой grain он
> несет и при каких проверках его можно публиковать.

**Тип:** Learn  
**Треки:** Data  
**Пререквизиты:** 07/10 - Quality gates  
**Время:** ~75 минут  
**Результат:** проектирует raw, staging, intermediate и mart слои: фиксирует grain,
ключи, владельца, freshness, допустимые изменения схемы и правила публикации
аналитической витрины.

## Цели обучения

- Разделить raw, staging, intermediate и mart слои по ответственности, а не по вкусу в
  названии папок.
- Зафиксировать grain, primary key, upstream models, owner, freshness и limitations до
  первого dbt-проекта.
- Отличить contract gates от warning diagnostics.
- Проверить, что mart не читает raw-источники напрямую и не пропускает layer checks.
- Выпустить machine-readable layer contract и design brief для будущего dbt graph.

## Проблема

Команда пишет SQL-запрос для `customer_revenue_health`:

```text
users
orders
order_items
events
support_tickets
```

Через неделю запрос копируют в notebook, потом в dashboard, потом в еще одну задачу. В
каждой копии чуть меняется фильтр `status`, join к `order_items` и обработка refund.
Один человек считает выручку по заказам, другой - по строкам заказа, третий исключает
удаленных пользователей. Все говорят "витрина пользователей", но у нее нет договора.

Analytics engineering начинается с другого вопроса:

```text
Какие модели существуют в графе и какую ответственность несет каждая?
```

Без этого dbt-проект быстро становится аккуратной папкой с неявной бизнес-логикой.

## Концепция

### Raw - не место для бизнес-решений

Raw source фиксирует внешний контракт:

```text
raw_orders
grain: one order
primary_key: order_id
freshness_column: updated_at
```

Raw слой не исправляет статусы, не решает, что такое paid revenue, и не делает join. Его
задача - быть честной границей с источником.

### Staging сохраняет source grain

Staging приводит имена, типы, timezone и enum-значения к рабочему виду:

```text
raw_orders -> stg_orders
```

Но staging не должен менять grain. Если `raw_orders` имеет одну строку на заказ, то
`stg_orders` тоже имеет одну строку на заказ. Иначе downstream модель уже не понимает,
какой уровень детализации она получила.

### Intermediate хранит переиспользуемую логику

Intermediate слой нужен, когда бизнес-правило повторяется:

```text
stg_orders + stg_order_items -> int_order_line_revenue
```

Здесь удобно проверять reconciliation: сумма `quantity * unit_price` должна совпадать с
`orders.amount`. Это не "косметика SQL", а gate перед mart.

### Mart - договор с потребителем

Mart уже отвечает на вопрос потребителя:

```text
mart_customer_revenue_health
grain: one registered user
consumers: finance_monthly_review, product_activation_review
publication: only after required tests pass
```

Если mart читает raw source напрямую, пропадает ценность графа: нормализация, проверки,
lineage и ревью становятся невидимыми.

### Contract gate не равен warning

Contract gate блокирует публикацию:

```text
primary key has nulls
duplicate user_id
revenue does not reconcile
raw source table is missing
```

Warning diagnostic остается видимым, но не всегда блокирует:

```text
freshness is close to SLA
support ticket rate watch
deleted user share changed
```

Оба типа проверок важны, но их нельзя смешивать. Иначе команда либо блокирует каждый
шорох, либо публикует витрину с реальным нарушением контракта.

## Соберите это

В этом уроке вы не запускаете dbt. Сначала соберите минимальный граф слоев как данные.

### Шаг 1: опишите raw sources

Откройте `../data/contract.json`. В нем raw tables объявлены независимо от будущих
моделей:

```json
"raw_orders": {
  "grain": "one order or marketplace payment",
  "primary_key": ["order_id"],
  "freshness_column": "updated_at"
}
```

Это источник правды для того, какие таблицы вообще можно читать.

### Шаг 2: опишите модели графа

Откройте `outputs/layer_contract.json`. Для каждой модели есть:

```text
model_id
layer
owner
grain
primary_key
source_tables
upstream_models
materialization
required_tests
warning_checks
publication_rule
known_limitations
```

Обратите внимание на разделение:

```text
source_tables: raw lineage
upstream_models: dependencies inside the model graph
```

Оба поля нужны. Первое помогает понять происхождение данных, второе - порядок
преобразований.

### Шаг 3: проверьте layer order

Запустите:

```bash
python outputs/layer_contract_auditor.py \
  --contract outputs/layer_contract.json \
  --data-contract ../data/contract.json \
  --brief outputs/mart_design_brief.md \
  --output outputs/layer_contract_audit.json
```

Валидный результат содержит:

```json
{
  "valid": true,
  "summary": {
    "models": 8,
    "layers": {
      "raw": 3,
      "staging": 3,
      "intermediate": 1,
      "mart": 1
    }
  }
}
```

### Шаг 4: прочитайте design brief

`outputs/mart_design_brief.md` - короткий handoff для человека. Он обязан назвать
business question, layer map и publication rule. Machine-readable contract защищает
структуру, а brief защищает смысл.

## Используйте это

В следующих уроках этот contract станет dbt graph:

```text
raw_orders              -> source('raw', 'orders')
stg_orders              -> ref('stg_orders')
int_order_line_revenue  -> ref('int_order_line_revenue')
mart_customer_revenue_health
```

dbt даст:

```text
parse
compile
run
test
docs generate
manifest.json
```

Но dbt не решит за вас, где меняется grain, какие tests блокируют публикацию и кто
владеет mart. Поэтому первый артефакт фазы - не SQL-файл, а contract.

Проверьте пример:

```bash
python code/main.py
```

Он импортирует аудитор и печатает compact summary слоя.

## Сломайте это

Попробуйте локально испортить копию `layer_contract.json`.

### Mart читает raw напрямую

Плохой вариант:

```json
"upstream_models": ["raw_orders"]
```

Аудитор должен провалить checks:

```text
layer_order_is_forward
mart_does_not_skip_layers
```

### У модели исчезли key tests

Плохой вариант:

```json
"required_tests": ["amount_reconciles_to_items"]
```

Для модели с primary key должны быть проверки:

```text
not_null_primary_key
unique_primary_key
```

### Brief не называет mart

Если design brief не упоминает `mart_customer_revenue_health`, handoff становится
декоративным. Человек не увидит, какая именно витрина публикуется.

## Проверьте это

Behavioral tests проверяют:

- все model ids уникальны;
- required fields есть у каждой модели;
- `source_tables` существуют в `../data/contract.json`;
- raw primary keys совпадают с data contract;
- non-raw models объявляют upstream dependencies;
- зависимости идут вперед: raw -> staging -> intermediate -> mart;
- mart не пропускает intermediate слой;
- модели с primary key имеют key tests;
- mart имеет owner, docs, exposures, publication rule и reconciliation;
- design brief содержит обязательные разделы и имя mart.

Запуск:

```bash
python -m unittest discover -s tests
```

## Поставьте результат

Итоговый артефакт:

```text
outputs/layer_contract_auditor.py
```

Он работает отдельно от текста урока:

```bash
python outputs/layer_contract_auditor.py \
  --contract outputs/layer_contract.json \
  --data-contract ../data/contract.json \
  --brief outputs/mart_design_brief.md \
  --output outputs/layer_contract_audit.json
```

Передайте вместе с ним:

```text
outputs/layer_contract.json
outputs/mart_design_brief.md
outputs/layer_contract_audit.json
```

Это стартовый договор фазы 11. Следующий урок превратит его в структуру dbt-проекта.

## Упражнения

1. Добавьте модель `stg_subscriptions`: сохраните grain `one subscription period`,
   объявите upstream `raw_subscriptions` и key tests.
2. Добавьте warning check для `raw_orders`: freshness close to SLA. Объясните, почему
   это warning, а не publication gate.
3. Создайте плохую mart-модель, которая читает `raw_order_items` напрямую, и проверьте,
   какие checks должны упасть.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Raw layer | Просто папка с исходными файлами | Граница с источником, где фиксируются schema, grain, key и freshness |
| Staging layer | Место для любой очистки | Нормализация источника без изменения source grain и бизнес-агрегации |
| Intermediate layer | Необязательный мусорный слой | Переиспользуемые join/aggregation steps с явным grain и проверками |
| Mart | Любая финальная таблица | Потребительская модель с владельцем, grain, tests, docs, limitations и publication rule |
| Contract gate | Любая проверка качества | Блокирующая проверка, без которой модель нельзя публиковать |
| Warning diagnostic | Несерьезная ошибка | Видимый риск, который не всегда блокирует публикацию, но должен попасть в handoff |

## Дополнительное чтение

- [dbt: About dbt projects](https://docs.getdbt.com/docs/build/projects) — разберите, как dbt описывает project structure и почему слой contract позже ложится в
  `dbt_project.yml` и `models/`.
- [dbt: Sources](https://docs.getdbt.com/docs/build/sources) — изучите `source()`,
  source tests и freshness как будущую реализацию raw boundary.
- [dbt: ref](https://docs.getdbt.com/reference/dbt-jinja-functions/ref) — посмотрите, как `ref()` превращает upstream models в graph dependencies и порядок запуска.
- [dbt: About data tests](https://docs.getdbt.com/docs/build/data-tests) — свяжите contract gates из урока с generic и singular tests в следующих уроках.
