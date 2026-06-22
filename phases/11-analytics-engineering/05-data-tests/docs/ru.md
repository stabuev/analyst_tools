# Data tests

> Тест данных должен защищать контракт потребителя, а warning должен помогать разбираться, не ломая поставку без причины.

**Тип:** Build
**Треки:** Data
**Пререквизиты:** 11-analytics-engineering/04-models
**Время:** ~90 минут
**Результат:** добавляете generic и singular dbt data tests, запускаете freshness и получаете machine-readable отчет о contract gates и warning diagnostics.

## Цели обучения

- Объявить generic data tests через `data_tests` для `not_null`, `unique`, `relationships` и `accepted_values`.
- Написать singular SQL tests для бизнес-инварианта, который не выражается одной колонкой.
- Разделить blocking contract gates и non-blocking warning diagnostics через `severity: warn`.
- Запустить `dbt source freshness` и `dbt test --select test_type:data` на tiny-warehouse.
- Прочитать `manifest.json`, `run_results.json` и `sources.json` как проверяемый артефакт качества.

## Проблема

В прошлом уроке появилась витрина `mart_customer_revenue_health`. Она уже строится, но это еще не значит, что ей можно верить. Если `order_items` случайно размножит строки, revenue улетит вверх. Если в raw появится новый `status`, модель может тихо отнести деньги не туда. Если support ticket ссылается на неизвестного пользователя, downstream-аналитик увидит строку без владельца.

Опасность не в том, что dbt упадет. Опасность в том, что dbt успешно построит неверную витрину.

## Концепция

В dbt data test - это запрос, который возвращает плохие строки. Пустой результат означает pass. Непустой результат означает failure или warning, в зависимости от severity.

Есть два уровня:

- **Generic tests** - переиспользуемые проверки из YAML. В этом уроке это `not_null`, `unique`, `relationships`, `accepted_values`.
- **Singular tests** - отдельные SQL-файлы в `tests/`. Они нужны там, где правило является бизнес-инвариантом: например, paid revenue в mart должен сходиться с paid order amount в source.

Разделение по смыслу важнее разделения по синтаксису:

| Тип проверки | Что защищает | Что делать при падении |
|---|---|---|
| Contract gate | Grain, ключи, ссылки, допустимые категории, финансовую сверку | Блокировать публикацию и чинить вход или модель |
| Warning diagnostic | Подозрительный, но допустимый срез данных | Не блокировать, но отправить на triage |
| Freshness | Актуальность raw source | Разобраться с загрузкой или задержкой источника |

## Соберите это

Сначала соберите минимальную модель теста без dbt. Пусть есть таблица заказов:

```python
orders = [
    {"order_id": "o001", "status": "paid"},
    {"order_id": "o002", "status": "chargeback"},
]

allowed = {"paid", "refunded"}
failures = [row for row in orders if row["status"] not in allowed]
print(failures)
```

Если `failures` пустой, правило прошло. Если есть строки, это не комментарий к данным, а конкретные rows, которые нужно показать владельцу источника.

### Шаг 1. Generic tests как контракт колонок

В проекте `outputs/data_test_project` generic tests объявлены через современный ключ `data_tests`:

```yaml
columns:
  - name: order_id
    data_tests:
      - unique
      - not_null
  - name: user_id
    data_tests:
      - relationships:
          arguments:
            to: ref('stg_users')
            field: user_id
  - name: status
    data_tests:
      - accepted_values:
          arguments:
            values: ['paid', 'refunded']
```

Это не просто "проверки для красоты". Здесь фиксируется контракт grain и домена: один order_id, непустой ключ, известный пользователь, разрешенный статус.

### Шаг 2. Singular test для reconciliation

Файл `tests/assert_paid_revenue_reconciles.sql` сравнивает две независимые суммы:

- `sum(paid_revenue_rub)` в mart;
- `sum(order amount * rate_to_rub)` по paid source orders.

Если разница больше `0.01`, тест возвращает строку с observed/expected/difference. Такой тест ловит ошибку, которую не поймает `not_null`: модель может быть заполнена, но сумма денег будет неправильной.

### Шаг 3. Warning diagnostic

Файл `tests/warn_customers_without_subscription.sql` начинается с:

```sql
{{ config(severity = 'warn') }}
```

Он показывает клиентов без subscription context или с support tickets. Это полезный сигнал для разбора customer health, но он не доказывает поломку витрины. Поэтому тест должен warning-ить, а не блокировать.

## Используйте это

Запустите урок из папки `phases/11-analytics-engineering/05-data-tests`:

```bash
uv run --locked python outputs/dbt_test_reporter.py \
  --project outputs/data_test_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Репортер делает четыре действия:

1. Статически проверяет YAML и SQL: есть все generic families, singular tests задокументированы, warnings помечены как `severity: warn`.
2. Создает временную DuckDB-базу из `../data/tiny/*.csv`.
3. Запускает `dbt parse`, `dbt run`, `dbt source freshness`, `dbt test --select test_type:data`.
4. Читает dbt artifacts и классифицирует результаты как `contract_gate` или `warning_diagnostic`.

Ожидаемый итог на baseline:

```json
{
  "test_kind_counts": {"generic": 64, "singular": 3},
  "test_status_counts": {"pass": 66, "warn": 1},
  "contract_failure_count": 0,
  "warning_diagnostic_count": 1
}
```

Один warning здесь нормален: диагностический тест нашел клиентов, которых нужно разобрать, но contract gates прошли.

## Сломайте это

Проверьте три характерных failure mode:

1. Замените один `status` в `raw_orders.csv` на `chargeback`. Должен упасть `accepted_values`.
2. Подставьте `user_id`, которого нет в `raw_users.csv`, в support ticket. Должен упасть `relationships`.
3. Измените `unit_price` в `raw_order_items.csv`, не меняя `raw_orders.amount`. Должен упасть singular reconciliation.

Важно: в каждом случае dbt-модели могут успешно построиться. Падает не build, а проверка данных.

## Проверьте это

Локальная проверка урока:

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked python code/main.py
```

Behavioral tests копируют dbt-проект во временную папку, портят YAML или tiny CSV и проверяют, что репортер ловит именно нужный тип ошибки. Это защищает урок от регрессии: нельзя случайно заменить `data_tests` на legacy `tests`, убрать freshness или превратить contract gate в warning.

## Поставьте результат

Именованный артефакт урока:

- `outputs/dbt_test_reporter.py` - CLI-аудитор dbt data tests.
- `outputs/dbt_test_report.json` - machine-readable статический отчет по baseline-проекту.
- `outputs/data_test_project/` - dbt-проект с generic и singular tests.

Команда для повторного использования:

```bash
python outputs/dbt_test_reporter.py \
  --project outputs/data_test_project \
  --data-contract ../data/contract.json \
  --run-dbt \
  --output outputs/dbt_test_report.json
```

В реальном проекте такой отчет можно положить в CI artifact: он объясняет, что именно было проверено, какие тесты блокируют публикацию и какие предупреждения требуют triage.

## Упражнения

1. Добавьте `accepted_values` для `priority` в `stg_support_tickets` и обновите тесты репортера.
2. Напишите singular test, который проверяет, что refunded orders не попадают в paid revenue.
3. Переведите один warning diagnostic в contract gate и объясните, какой бизнес-аргумент оправдывает блокировку.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Data test | "Проверка схемы таблицы" | SQL-запрос, который возвращает проблемные строки |
| Generic test | "Встроенная магия dbt" | Параметризованная проверка, объявленная на resource/column в YAML |
| Singular test | "Любой ручной SQL" | Отдельный SQL-файл в `tests/`, который возвращает failures для конкретного правила |
| Severity warn | "Тест неважен" | Диагностика важна, но не должна блокировать поставку без подтвержденного нарушения контракта |
| Source freshness | "То же самое, что not_null" | Проверка задержки обновления source по `loaded_at_field` и порогам freshness |

## Дополнительное чтение

- [dbt Docs: Data tests](https://docs.getdbt.com/docs/build/data-tests) — основной раздел о generic и singular data tests, включая современный ключ `data_tests`.
- [dbt Reference: Data test severity](https://docs.getdbt.com/reference/resource-configs/severity) — как работают `severity`, `warn_if` и `error_if`, и почему warning не равен ignored.
- [dbt Reference: dbt test](https://docs.getdbt.com/reference/commands/test) — параметры запуска тестов, включая выборку `test_type:data`.
- [dbt Reference: dbt source](https://docs.getdbt.com/reference/commands/source) — как запускать `dbt source freshness` и где dbt сохраняет `sources.json`.
