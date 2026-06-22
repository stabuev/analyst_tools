# Jinja и macros без злоупотребления

> Macro полезен только тогда, когда compiled SQL становится понятнее, а не загадочнее.

**Тип:** Learn
**Треки:** Data
**Пререквизиты:** 11-analytics-engineering/05-data-tests
**Время:** ~75 минут
**Результат:** выносите повторяемые SQL-правила в маленькие Jinja macros, документируете аргументы и проверяете compiled SQL перед тем, как доверить витрину потребителю.

## Цели обучения

- Объяснить, что Jinja в dbt рендерится в обычный SQL до выполнения модели.
- Написать маленькие macros для механических повторов: normalization, decimal cast, money arithmetic.
- Документировать macro arguments в `macros/properties.yml`.
- Проверить compiled SQL после `dbt compile`, а не ревьюить только source Jinja.
- Провести границу между полезной абстракцией и скрытой бизнес-логикой.

## Проблема

После урока про data tests проект уже строит и проверяет `mart_customer_revenue_health`. Но в SQL начали повторяться механические куски:

- `lower(status)`;
- `upper(currency)`;
- `cast(... as decimal(18, 2))`;
- `amount * rate_to_rub`;
- `quantity * unit_price`.

На таком месте хочется "сделать красиво" и завернуть все в macro. Это опасный момент. Если macro прячет только механический SQL, он уменьшает шум. Если macro прячет `revenue_health_segment`, paid/refund semantics или join grain, ревьюер перестает видеть самое важное правило витрины.

## Концепция

Jinja в dbt - это шаблонизация SQL. Source model содержит `{{ ... }}` и `{% ... %}`, а dbt компилирует его в обычный SQL в `target/compiled/<project>/...`.

В этом уроке есть три уровня решения:

| Уровень | Пример | Где держать |
|---|---|---|
| Механический повтор | `upper(currency)`, `cast(amount as decimal(18, 2))` | macro |
| Локальная формула без политики | `quantity * unit_price`, `amount * rate` | маленький macro с понятным именем |
| Бизнес-правило | `revenue_health_segment`, paid/refund semantics | явно в model SQL |

Правило простое: если для проверки macro нужно открыть пять файлов и помнить контекст бизнеса, macro слишком много знает.

## Соберите это

Сначала посмотрите на macro как на обычную функцию, которая печатает SQL:

```python
def to_decimal(column_name: str, precision: int = 18, scale: int = 2) -> str:
    return f"cast({column_name} as decimal({precision}, {scale}))"

print(to_decimal("amount"))
```

Результат:

```sql
cast(amount as decimal(18, 2))
```

Это весь механизм. Macro не считает деньги сам. Он только возвращает SQL-фрагмент.

### Шаг 1. Маленький macro

В `outputs/macro_project/macros/normalization.sql`:

```sql
{%- macro normalize_currency(column_name) -%}
upper({{ column_name }})
{%- endmacro -%}
```

В модели:

```sql
{{ normalize_currency('currency') }} as currency
```

После `dbt compile` это должно стать обычным SQL:

```sql
upper(currency) as currency
```

Кавычки вокруг `'currency'` важны: внутри Jinja это строковый аргумент. Без кавычек Jinja будет искать переменную `currency`.

### Шаг 2. Macro docs

В `macros/properties.yml` каждый macro описывает аргументы:

```yaml
macros:
  - name: to_decimal
    description: "Casts a numeric column or expression to a DuckDB decimal."
    arguments:
      - name: column_name
        type: column
        description: "Column or SQL expression to cast."
      - name: precision
        type: integer
        description: "Total decimal precision. Defaults to 18."
```

Документация нужна не для галочки. Она объясняет, что macro принимает, где его можно применять и где нельзя.

### Шаг 3. Граница абстракции

В проекте есть `rub_amount(amount_column, rate_column)`, но нет macro для `revenue_health_segment`. Конвертация валюты - механическая арифметика. Сегментация клиента - бизнес-решение:

```sql
case
    when coalesce(sum(orders.refunded_amount_rub), 0) > 0
        or coalesce(max(support.support_ticket_count), 0) > 0
        then 'needs_attention'
    when coalesce(sum(orders.paid_revenue_rub), 0) >= 2000
        then 'high_value'
    when coalesce(sum(orders.paid_revenue_rub), 0) > 0
        then 'monetized'
    else 'no_revenue'
end as revenue_health_segment
```

Это должно оставаться в mart-модели, рядом с joins, grain и агрегатами.

## Используйте это

Запустите из папки `phases/11-analytics-engineering/06-macros`:

```bash
uv run --locked python outputs/macro_review_auditor.py \
  --project outputs/macro_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Аудитор делает две группы проверок.

Статически:

- находит macro definitions и их arguments;
- сравнивает arguments с `macros/properties.yml`;
- считает ожидаемые macro calls;
- проверяет `compiled_sql_review_checklist.json`;
- запрещает macro names, которые прячут customer health или segmentation policy.

В live-режиме:

- создает временную DuckDB-базу из `../data/tiny`;
- запускает `dbt parse`, `dbt compile`, `dbt run`, `dbt test --select test_type:data`;
- читает compiled SQL для 13 model files;
- проверяет, что Jinja исчез, SQL-фрагменты читаемы, а mart по-прежнему дает 5 строк и `4312.50` RUB paid revenue.

## Сломайте это

Проверьте четыре поломки:

1. Удалите `rub_amount` из `macros/properties.yml`. Аудитор должен упасть на документации аргументов.
2. Замените один вызов `normalize_currency` обратно на inline `upper(currency)`. Аудитор покажет, что macro suite используется непоследовательно.
3. Добавьте macro `customer_health_segment`. Аудитор отклонит его как скрытую бизнес-логику.
4. Поменяйте `rub_amount` с умножения на деление. `dbt test` и revenue reconciliation должны заблокировать результат.

## Проверьте это

Локальная проверка урока:

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked python code/main.py
```

`code/main.py` выводит compact report:

```json
{
  "valid": true,
  "compiled_models": 13,
  "mart_output": {"row_count": 5, "paid_revenue_rub": "4312.50"},
  "checks": "13/13"
}
```

Тесты специально портят macro docs, source SQL и macro implementation. Так урок проверяет не только "dbt compiled", но и то, что abstraction boundary остается человеческой.

## Поставьте результат

Именованный артефакт:

- `outputs/macro_review_auditor.py` - CLI-аудитор macro suite и compiled SQL.
- `outputs/macro_review_report.json` - deterministic static report.
- `outputs/compiled_sql_review_checklist.json` - чеклист ревью compiled SQL.
- `outputs/macro_project/` - dbt-проект с documented macros.

Команда для CI artifact:

```bash
python outputs/macro_review_auditor.py \
  --project outputs/macro_project \
  --data-contract ../data/contract.json \
  --run-dbt \
  --output outputs/macro_review_report.json
```

В реальном проекте такой gate помогает не превратить dbt в набор невидимых шаблонов: reviewer видит и source Jinja, и compiled SQL.

## Упражнения

1. Добавьте macro `to_timestamp_tz(column_name)` и объясните, почему это mechanical abstraction.
2. Попробуйте вынести `revenue_health_segment` в macro, затем напишите ревью-комментарий, почему это ухудшило модель.
3. Добавьте правило в `compiled_sql_review_checklist.json`, которое ограничивает максимальную длину compiled mart SQL.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Jinja | "SQL с Python внутри" | Шаблонизатор, который рендерит текст SQL до выполнения |
| Macro | "Любая абстракция лучше копипаста" | Переиспользуемый SQL-шаблон, который должен сохранять compiled SQL читаемым |
| Compiled SQL | "Временный мусор dbt" | SQL, который реально будет выполнен warehouse и который нужно ревьюить при сложном Jinja |
| Macro arguments | "Необязательная документация" | Контракт входов macro: имена, типы и смысл аргументов |
| Readability over DRY | "Можно повторять что угодно" | Повтор допустим, если abstraction сделает бизнес-логику менее видимой |

## Дополнительное чтение

- [dbt Docs: Jinja and macros](https://docs.getdbt.com/docs/build/jinja-macros) - основной раздел о Jinja, macros, compiled SQL, quoting и принципе readability over DRY.
- [dbt Reference: arguments for macros](https://docs.getdbt.com/reference/resource-properties/arguments) - как документировать macro arguments, типы и validation behavior.
- [dbt Reference: dbt compile](https://docs.getdbt.com/reference/commands/compile) - зачем запускать compile, где искать `target/compiled` и как использовать его для ревью Jinja.
- [Jinja Template Designer: Whitespace Control](https://jinja.palletsprojects.com/en/stable/templates/#whitespace-control) - как работают `-` в `{%- ... -%}` и почему compiled SQL может получить лишние пустые строки.
