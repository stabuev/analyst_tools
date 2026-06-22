# Инкрементальные модели

> Incremental-модель ускоряет пересчет только тогда, когда у нее есть явный ключ, окно поздних данных и понятная политика full refresh.

**Тип:** Build
**Треки:** Data
**Пререквизиты:** 11-analytics-engineering/06-macros
**Время:** ~90 минут
**Результат:** проектируете incremental mart с `is_incremental()`, `unique_key`, late-arrival window, full-refresh policy и тестами против дубликатов, пропущенных обновлений и schema change.

## Цели обучения

- Объяснить, когда incremental materialization безопаснее полного пересчета, а когда опаснее.
- Спроектировать grain и `unique_key` до написания фильтра обновления.
- Написать dbt-модель с `is_incremental()`, `{{ this }}` и окном поздних данных.
- Зафиксировать full-refresh/backfill policy рядом с моделью.
- Проверить incremental run на сценарии "новая дата плюс поздно пришедший заказ".

## Проблема

`mart_customer_revenue_health` из прошлых уроков можно пересчитывать целиком: данных мало, логика компактная. Но дневная fact-витрина выручки в реальном проекте быстро становится тяжелой. Каждый день добавляются новые заказы, иногда старые даты получают поздние строки, refund может приехать после платежа, а отчет finance хочет стабильную таблицу.

Наивная оптимизация звучит так: "будем добавлять только новые строки". В ней сразу три риска:

- без `unique_key` повторный запуск создает дубликаты по дате;
- без late-arrival window заказ за прошлую дату не попадет в витрину;
- без full-refresh policy изменение логики конвертации валюты исправит только новые дни, а история останется старой.

В этом уроке вы строите `fct_order_revenue_daily`: одну строку на `revenue_date`, инкрементальное обновление с двухдневным окном и проверяемый playbook для backfill.

## Концепция

Incremental-модель в dbt материализуется как таблица. Первый запуск строит ее полностью. Следующие запуски могут обработать только подмножество входных строк и применить результат к уже существующей таблице.

Для такой модели нужен не один SQL-фильтр, а договор:

| Решение | Вопрос | Ошибка без него |
|---|---|---|
| Grain | Что означает одна строка target-таблицы? | Нельзя понять, что считать дублем |
| `unique_key` | По какому ключу обновлять уже существующую строку? | Append-only поведение копит повторы |
| Incremental predicate | Какие source-строки пересчитывать на обычном запуске? | Старые даты не обновляются или пересчитывается слишком много |
| Late-arrival window | Насколько назад смотреть из-за задержек данных? | Поздний заказ или refund не попадет в витрину |
| Schema change policy | Что делать при изменении набора колонок? | История и новая схема расходятся молча |
| Full-refresh policy | Когда перестроить всю таблицу с нуля? | Исторические ошибки остаются вне окна |

`is_incremental()` должен компилироваться в валидный SQL в обеих ветках. Он становится true, когда target relation уже существует, модель настроена как incremental и запуск не идет с `--full-refresh`. Поэтому фильтр обычно пишут так, чтобы первый запуск не зависел от `{{ this }}`, а incremental-запуск читал максимум из уже построенной таблицы.

## Соберите это

Сначала разберите механизм без dbt. Есть текущая target-таблица:

```text
revenue_date | paid_revenue_rub
2026-05-02   | 1200.00
2026-05-03   | 800.00
2026-05-04   | 0.00
```

Новая source-выгрузка содержит:

```text
o004 | 2026-05-07 | paid | 2312.50
o005 | 2026-05-03 | paid | 100.00
```

`o005` пришел поздно: дата заказа 2026-05-03, но загрузили его после первой сборки. Если фильтровать только `order_date > max(revenue_date)`, модель увидит 2026-05-07 и пропустит 2026-05-03.

### Шаг 1. Назовите grain и ключ

Для дневной fact-витрины grain:

```text
one calendar revenue date
```

Ключ:

```text
unique_key = revenue_date
```

Это значит: при пересчете 2026-05-03 новая строка должна заменить старую строку за 2026-05-03, а не добавиться второй строкой.

### Шаг 2. Выберите окно поздних данных

В учебном датасете задержка маленькая, поэтому используем два дня назад от максимальной даты в target:

```sql
where orders.order_date >= (
    select coalesce(max(revenue_date) - interval '2 days', date '1900-01-01') from target_table
)
```

Если target пустой, `coalesce` дает безопасную нижнюю границу. Если target уже содержит максимум 2026-05-04, окно начинается с 2026-05-02 и поздний заказ на 2026-05-03 попадет в пересчет.

### Шаг 3. Смоделируйте delete+insert

Минимальный алгоритм:

```python
target = {
    "2026-05-02": 1200.00,
    "2026-05-03": 800.00,
    "2026-05-04": 0.00,
}

recalculated_window = {
    "2026-05-02": 1200.00,
    "2026-05-03": 900.00,
    "2026-05-04": 0.00,
    "2026-05-07": 2312.50,
}

for revenue_date in recalculated_window:
    target.pop(revenue_date, None)
target.update(recalculated_window)
```

После обновления 2026-05-03 равен `900.00`, а не двум строкам `800.00` и `100.00`. Это и есть смысл `unique_key` плюс incremental strategy: обновлять набор ключей, который модель пересчитала.

## Используйте это

Готовый dbt-проект лежит в `outputs/incremental_project`. Ключевая модель:

```sql
{{
    config(
        materialized='incremental',
        unique_key='revenue_date',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}
```

Фильтр внутри модели:

```sql
{% if is_incremental() %}
where orders.order_date >= (
    select coalesce(max(revenue_date) - interval '2 days', date '1900-01-01') from {{ this }}
)
{% endif %}
```

Контракт повторен в `models/properties.yml`:

```yaml
meta:
  incremental_contract:
    event_time_column: revenue_date
    unique_key: revenue_date
    late_arrival_window_days: 2
    incremental_strategy: delete+insert
    schema_change_policy: fail
    backfill_command: "dbt run --full-refresh --select fct_order_revenue_daily"
```

Запустите из папки `phases/11-analytics-engineering/07-incremental-models`:

```bash
uv run --locked python outputs/incremental_model_auditor.py \
  --project outputs/incremental_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Аудитор делает три live-шага:

1. Собирает начальную базу без `o004`: `3` дневные строки, `2000.00` RUB paid revenue.
2. Подменяет raw-таблицы на полную выгрузку и добавляет поздний `o005` на 2026-05-03.
3. Запускает обычный `dbt run`, проверяет incremental result и затем документированный `--full-refresh`.

Ожидаемый итог:

```json
{
  "row_count": 4,
  "paid_revenue_rub": "4412.50",
  "may_03_paid_revenue_rub": "900.00",
  "duplicate_date_rows": 0
}
```

## Сломайте это

Проверьте пять поломок:

1. Удалите `unique_key='revenue_date'` из модели. Статический auditor должен отклонить модель до запуска dbt.
2. Замените `{{ this }}` на literal table name. Auditor покажет, что модель больше не переносима между окружениями.
3. Измените `interval '2 days'` на `interval '0 days'`. Поздний заказ на 2026-05-03 больше не входит в окно.
4. Уберите `unique` test с `revenue_date`. Контракт ключа станет декларацией без проверки.
5. Перепишите playbook без `--full-refresh`. Команда потеряет правило, когда история должна быть перестроена.

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
  "incremental_fct_output": {
    "row_count": 4,
    "paid_revenue_rub": "4412.50",
    "may_03_paid_revenue_rub": "900.00",
    "duplicate_date_rows": 0
  },
  "checks": "15/15"
}
```

Data test `tests/assert_daily_revenue_reconciles.sql` сверяет дневную витрину с source-level расчетом из `stg_orders` и `stg_currency_rates`. Это важно: successful `dbt run` означает только "SQL выполнился", а не "инкрементальная логика не пропустила старую дату".

## Поставьте результат

Именованный артефакт:

- `outputs/incremental_model_auditor.py` - CLI-аудитор incremental contract и live late-arrival behavior.
- `outputs/incremental_audit_report.json` - deterministic static report.
- `outputs/backfill_full_refresh_playbook.md` - full-refresh/backfill policy для модели.
- `outputs/incremental_project/` - dbt-проект с `fct_order_revenue_daily`.

Команда для CI artifact:

```bash
python outputs/incremental_model_auditor.py \
  --project outputs/incremental_project \
  --data-contract ../data/contract.json \
  --run-dbt \
  --output outputs/incremental_audit_report.json
```

В рабочем проекте такой gate полезен перед merge: он проверяет не только наличие `materialized='incremental'`, но и операционный договор, из-за которого модель можно безопасно поддерживать.

## Упражнения

1. Добавьте колонку `gross_revenue_rub` в source reconciliation test и проверьте, что refund-дни не ломают paid revenue.
2. Смените grain на `revenue_date, currency` и перечислите, какие места контракта должны измениться.
3. Добавьте второй поздний заказ за дату вне двухдневного окна и опишите, почему для него нужен backfill/full refresh, а не обычный incremental run.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Incremental model | "dbt сам поймет, что изменилось" | Таблица, которую модель обновляет по явно заданной логике и стратегии |
| `is_incremental()` | "Условие для ускорения любого SQL" | Jinja-предикат, который true только при существующей incremental relation и запуске без `--full-refresh` |
| `unique_key` | "Просто документация ключа" | Ключ, по которому adapter может обновлять уже существующие строки вместо append-дубликатов |
| Late-arrival window | "Запас на всякий случай" | Осознанный исторический интервал, который обычный incremental run пересчитывает из-за задержек данных |
| Full refresh | "Аварийная кнопка" | Операционный режим перестроения всей incremental table, нужный после изменений логики, grain, key или исторического backfill |
| `on_schema_change` | "Автоматическое исправление истории" | Политика реакции на изменение колонок; она не заменяет backfill старых строк |

## Дополнительное чтение

- [dbt Docs: Incremental models](https://docs.getdbt.com/docs/build/incremental-models) — прочитайте условия `is_incremental()`, пример фильтра по max timestamp и предупреждения про late-arriving facts.
- [dbt Docs: Incremental strategy](https://docs.getdbt.com/docs/build/incremental-strategy) — сравните стратегии adapter'ов и проверьте, какая стратегия доступна в вашем warehouse.
- [dbt Reference: unique_key](https://docs.getdbt.com/reference/resource-configs/unique_key) — разберите, почему ключевые колонки не должны быть null и как задавать составной ключ.
- [dbt Reference: run command](https://docs.getdbt.com/reference/commands/run) — посмотрите, как `--full-refresh` меняет поведение incremental-моделей и почему это часть runbook.
