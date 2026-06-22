# Snapshots и история изменений

> Snapshot сохраняет историю mutable source только в те моменты, когда вы действительно запускаете `dbt snapshot`.

**Тип:** Build
**Треки:** Data
**Пререквизиты:** 11-analytics-engineering/07-incremental-models
**Время:** ~75 минут
**Результат:** используете dbt snapshots для SCD type 2 истории mutable source tables и проверяете unique key, updated_at/check strategy, validity windows и исключение шумных колонок.

## Цели обучения

- Объяснить, зачем SCD type 2 нужен для mutable source tables.
- Настроить YAML snapshot с `unique_key`, `strategy: check`, `updated_at` и явным `check_cols`.
- Превратить snapshot meta-fields в читаемую history-модель с `valid_from`, `valid_to` и `is_current`.
- Проверить, что у каждой подписки ровно одна текущая версия и окна истории не пересекаются.
- Отличить бизнес-изменение от шумного обновления `updated_at`.

## Проблема

В прошлых уроках `stg_subscriptions` показывал текущее состояние подписки. Это удобно для витрины "кто сейчас active", но плохо для вопросов про историю:

- когда пользователь перешел с `basic` на `plus`;
- сколько времени подписка была active перед cancel;
- какой план был у пользователя на дату заказа;
- почему вчерашний отчет уже нельзя пересчитать из сегодняшней source-таблицы.

Source `raw_subscriptions` mutable: строка с тем же `subscription_id` может быть перезаписана. Если не сохранять прошлую версию, история исчезает. Snapshot решает эту задачу как SCD type 2: вместо одной перезаписанной строки появляются версии с интервалами валидности.

## Концепция

SCD type 2 хранит не "текущее значение", а последовательность версий:

| subscription_id | plan | status | valid_from | valid_to | is_current |
|---|---|---|---|---|---|
| s002 | basic | active | 2026-05-20 | 2026-05-22 | false |
| s002 | plus | active | 2026-05-22 | 9999-12-31 | true |

У snapshot есть три обязательных решения:

| Решение | Вопрос | Ошибка без него |
|---|---|---|
| `unique_key` | Как сопоставить новую source-строку со старой snapshot-версией? | dbt не знает, какую строку закрывать |
| Strategy | Как понять, что row state изменился? | История либо не обновляется, либо версионирует шум |
| Schedule | Как часто фиксировать состояния? | Изменения между запусками теряются |

В dbt есть две основные стратегии:

- `timestamp`: смотрит на один `updated_at`; это рекомендуемый default, когда source timestamp надежен.
- `check`: сравнивает список `check_cols`; полезно, когда `updated_at` может меняться без бизнес-изменения.

В этом уроке используем `check` вместе с `updated_at`. Так snapshot создает новую версию только при изменении `plan`, `status`, `started_at` или `ended_at`, но timestamps версий берет из source `updated_at`.

## Соберите это

Сначала смоделируйте механизм без dbt. Начальное состояние:

```text
s001 | plus    | active
s002 | basic   | active
s003 | plus    | cancelled
s004 | premium | active
```

После следующей выгрузки:

```text
s001 | plus    | active     | updated_at сдвинулся, бизнес-поля те же
s002 | plus    | active     | plan изменился
s003 | plus    | cancelled  | без изменения
s004 | premium | cancelled  | status и ended_at изменились
s005 | basic   | active     | новая подписка
```

### Шаг 1. Найдите changed keys

Сравните только бизнес-поля:

```python
check_cols = ["plan", "status", "started_at", "ended_at"]
```

Результат:

- `s001` не меняется, потому что изменился только `updated_at`;
- `s002` получает новую версию из-за `plan`;
- `s004` получает новую версию из-за `status` и `ended_at`;
- `s005` вставляется как новый current row.

### Шаг 2. Закройте старые окна

Для измененных ключей старая версия получает `valid_to` равный времени новой версии:

```text
s002 basic active valid_to = 2026-05-22 08:00
s004 premium active valid_to = 2026-05-21 09:30
```

Новые версии получают `valid_to = 9999-12-31`, чтобы current-фильтр был обычным сравнением, а не `is null`.

### Шаг 3. Проверьте инварианты

История корректна, если:

- у каждого `subscription_id` ровно одна current-строка;
- `valid_to` закрытой версии равен `valid_from` следующей версии;
- `dbt_scd_id` уникален;
- шумный `updated_at` без изменения `check_cols` не создает новую версию.

## Используйте это

Готовый dbt-проект лежит в `outputs/snapshot_project`. Snapshot объявлен в YAML:

```yaml
snapshots:
  - name: subscription_status_snapshot
    relation: ref('stg_subscriptions')
    config:
      target_schema: snapshots
      unique_key: subscription_id
      strategy: check
      updated_at: updated_at
      check_cols:
        - plan
        - status
        - started_at
        - ended_at
      dbt_valid_to_current: "cast('9999-12-31' as timestamp)"
```

Downstream-модель `int_subscription_history` делает meta-fields читаемыми:

```sql
select
    subscription_id,
    plan,
    status,
    cast(dbt_valid_from as timestamp) as valid_from,
    cast(dbt_valid_to as timestamp) as valid_to,
    dbt_scd_id,
    cast(dbt_valid_to as timestamp) = timestamp '9999-12-31 00:00:00' as is_current
from {{ ref('subscription_status_snapshot') }}
```

Запустите из папки `phases/11-analytics-engineering/08-snapshots`:

```bash
uv run --locked python outputs/snapshot_history_auditor.py \
  --project outputs/snapshot_project \
  --data-contract ../data/contract.json \
  --run-dbt
```

Аудитор делает два цикла:

1. Загружает исходные subscriptions, запускает `dbt run`, `dbt snapshot`, `dbt run --select int_subscription_history` и data tests.
2. Подменяет source на новую выгрузку, где `s002` меняет план, `s004` отменяется, `s005` появляется, а у `s001` меняется только `updated_at`.

Ожидаемый итог второго цикла:

```json
{
  "row_count": 7,
  "subscription_count": 5,
  "current_rows": 5,
  "closed_rows": 2,
  "s001_versions": 1,
  "s002_versions": 2,
  "s004_versions": 2,
  "s005_versions": 1,
  "overlap_count": 0
}
```

## Сломайте это

Проверьте пять поломок:

1. Удалите `unique_key`. Snapshot больше не имеет надежного способа закрывать старую версию.
2. Поставьте `check_cols: all`. Шумные технические изменения начнут создавать лишние версии.
3. Добавьте `updated_at` в `check_cols`. `s001` получит новую версию без бизнес-изменения.
4. Уберите `dbt_valid_to_current`. Текущие строки снова станут `NULL`, и downstream-фильтр нужно будет переписать.
5. Запустите `dbt snapshot` реже, чем меняется source. Состояния между двумя запусками не появятся в истории.

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
  "changed_history_output": {
    "row_count": 7,
    "subscription_count": 5,
    "current_rows": 5,
    "closed_rows": 2,
    "s001_versions": 1,
    "s002_versions": 2,
    "s004_versions": 2,
    "s005_versions": 1,
    "overlap_count": 0
  },
  "checks": "18/18"
}
```

Singular tests:

- `assert_subscription_history_has_one_current_row.sql`;
- `assert_subscription_history_windows_do_not_overlap.sql`;
- `assert_snapshot_does_not_version_noisy_updated_at.sql`.

Они проверяют поведение истории, а не только успешное выполнение `dbt snapshot`.

## Поставьте результат

Именованный артефакт:

- `outputs/snapshot_history_auditor.py` - CLI-аудитор snapshot/SCD history contract.
- `outputs/snapshot_history_audit_report.json` - deterministic static report.
- `outputs/snapshot_history_runbook.md` - run order, schedule и hard delete policy.
- `outputs/snapshot_project/` - dbt-проект с YAML snapshot и history-моделью.

Команда для CI artifact:

```bash
python outputs/snapshot_history_auditor.py \
  --project outputs/snapshot_project \
  --data-contract ../data/contract.json \
  --run-dbt \
  --output outputs/snapshot_history_audit_report.json
```

В рабочем проекте такой gate помогает не принять snapshot, который выглядит SCD-моделью, но на деле версионирует технический шум или теряет validity windows.

## Упражнения

1. Переведите snapshot на `strategy: timestamp` и объясните, почему `s001` начнет или не начнет версионироваться.
2. Добавьте soft-delete колонку в source и включите ее в `check_cols`.
3. Напишите point-in-time join: какой план был у пользователя на дату заказа из `fct_order_revenue_daily`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Snapshot | "Автоматическая история всех изменений" | Batch-механизм, который фиксирует только состояния, увиденные при запуске `dbt snapshot` |
| SCD type 2 | "Еще одна копия таблицы" | История версий строки с интервалами валидности |
| `unique_key` | "Тест уникальности" | Ключ сопоставления текущей source-строки и последней snapshot-версии |
| `check_cols` | "Можно поставить `all` и забыть" | Явный список бизнес-полей, изменение которых должно создавать новую версию |
| `updated_at` в check strategy | "Колонка, которую тоже надо сравнивать" | Timestamp, которым dbt датирует новые версии, если `check_cols` изменились |
| `dbt_valid_to_current` | "Косметика вместо NULL" | Sentinel для current-строк, упрощающий date range filters |
| Hard delete | "Snapshot сам поймет удаление" | Отдельная opt-in политика; без нее исчезнувшие source-строки не становятся историей удаления |

## Дополнительное чтение

- [dbt Docs: Snapshots](https://docs.getdbt.com/docs/build/snapshots) — прочитайте sections про SCD type 2, стратегии, `dbt_valid_to_current`, unique key и schedule.
- [dbt Reference: Snapshot configurations](https://docs.getdbt.com/reference/snapshot-configs) — посмотрите актуальный YAML-формат snapshots, migration notes и место snapshot configs в проекте.
- [dbt Reference: snapshot command](https://docs.getdbt.com/reference/commands/snapshot) — разберите запуск `dbt snapshot`, `--select` и связь с `snapshot-paths`.
- [Wikipedia: Slowly changing dimension](https://en.wikipedia.org/wiki/Slowly_changing_dimension) — используйте как словарь типов SCD и сравните type 1/type 2.
