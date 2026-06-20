# Когортный анализ

> Когортная матрица честна только тогда, когда у каждой ячейки есть фиксированный знаменатель и явный признак полноты окна наблюдения.

**Тип:** Build
**Треки:** Product
**Пререквизиты:** 08-product-analytics/04-funnels
**Время:** ~75 минут
**Результат:** вы соберете CLI-калькулятор daily cohort matrix по registered users и active events, не смешивая нулевую активность с неполным наблюдением.

## Цели обучения

- Назначать пользователя в когорту по `registered_at` в business timezone.
- Строить полную матрицу `cohort_date x age_day`, включая нулевые ячейки.
- Считать `activity_rate` на фиксированном `cohort_size` и не заполнять rate для incomplete windows.
- Проверять duplicate delivery, late arrivals, test users и несовпадение active events с tracking plan.

## Проблема

После прошлых уроков команда уже знает активность и воронки. Теперь хочется понять, отличаются ли новые пользователи разных дней: например, пользователи 8 июня выглядят активными на day 0, но что с day 7?

Если просто построить таблицу по тем событиям, которые уже есть, можно получить красивую, но опасную матрицу. Для когорты 8 июня day 7 соответствует 15 июня, а в tiny-логе наблюдение заканчивается 9 июня. В такой ячейке нельзя писать `0%`: мы не знаем, вернулись ли пользователи 15 июня. Это не нулевая активность, а неполное окно.

В этом уроке cohort matrix становится технической основой для следующих расчетов retention и LTV: сначала фиксируем вход, возраст когорты, знаменатель и полноту наблюдения.

## Концепция

Когорта - группа единиц, которые вошли в продукт при одном условии и в одном периоде. Здесь:

```text
cohort_unit = user_id
cohort_start = registered_at
cohort_date = date(registered_at in Europe/Moscow)
age_day = activity_date - cohort_date
cohort_size = count(non-test users in cohort_date)
active_users = distinct users with active events in cohort_date + age_day
activity_rate = active_users / cohort_size, only when window is complete
```

Важно различать три состояния ячейки:

| Состояние | Пример | Что писать |
|---|---|---|
| Есть активность | `2026-06-01`, age 0: 2 активных из 2 | `1.000000` |
| Активности нет, окно завершено | `2026-06-01`, age 1: событий нет, дата уже наблюдалась | `0.000000` |
| Окно не завершено | `2026-06-08`, age 2: activity date `2026-06-10`, лог заканчивается `2026-06-09` | пустой `activity_rate`, `is_complete_window=false` |

Минимальная схема:

```text
users + events + tracking_plan + activity_spec + cohort_spec
  -> validate cohort spec and active event names
  -> deduplicate events by event_id
  -> exclude test users
  -> assign cohort_date from registered_at
  -> build full cohort_date x age_day grid
  -> mark complete windows against observation_end_date
  -> count distinct active users only inside complete cells
  -> emit cohorts.csv and quality report
```

## Соберите это

Начните с ручной проверки cohort sizes:

```python
cohort_size["2026-06-01"] = 2  # U001, U002
cohort_size["2026-06-02"] = 1  # U003
cohort_size["2026-06-03"] = 1  # U004
cohort_size["2026-06-04"] = 1  # U005
cohort_size["2026-06-05"] = 1  # U006
cohort_size["2026-06-08"] = 1  # U007
```

`U999` не входит в когорты, потому что это test user.

Запустите пример:

```bash
python3 code/main.py
```

Он печатает ручные cohort sizes и две контрольные ячейки:

```json
{
  "manual_cohort_sizes": {
    "2026-06-01": 2,
    "2026-06-02": 1,
    "2026-06-03": 1,
    "2026-06-04": 1,
    "2026-06-05": 1,
    "2026-06-08": 1
  },
  "first_cohort_day_zero": {
    "cohort_size": "2",
    "active_users": "2",
    "activity_rate": "1.000000"
  },
  "newest_cohort_age_two": {
    "activity_rate": "",
    "is_complete_window": "false"
  }
}
```

Ручной расчет объясняет denominator. CLI дальше обобщает это на полный grid и проверки качества.

## Используйте это

Рабочий артефакт:

```text
outputs/cohort_calculator.py
```

Запуск:

```bash
python3 outputs/cohort_calculator.py \
  --events ../data/tiny/events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --activity-spec ../03-activity/outputs/activity_spec.json \
  --spec outputs/cohort_spec.json \
  --output outputs/cohorts.csv \
  --report cohort-report.json
```

Фрагмент `cohorts.csv`:

```csv
metric_id,cohort_date,age_day,activity_date,cohort_size,active_users,activity_rate,is_complete_window,active_event_count
cohort_activity_matrix,2026-06-01,0,2026-06-01,2,2,1.000000,true,6
cohort_activity_matrix,2026-06-01,1,2026-06-02,2,0,0.000000,true,0
cohort_activity_matrix,2026-06-08,2,2026-06-10,1,0,,false,0
```

`cohort-report.json` фиксирует 48 строк матрицы, 6 когорт, 36 complete windows и 12 incomplete windows. Если report invalid, таблицу нельзя использовать как аргумент в продуктовой рекомендации.

## Сломайте это

Проверьте типовые ошибки:

- Удалите age 2 из `age_days`: матрица перестанет быть непрерывной, и report вернет failure.
- Добавьте duplicate `event_id=E031`: report станет invalid, но активность 5 июня не удвоится.
- Добавьте active event для test user `U999`: cohort sizes и activity counts не должны измениться.
- Сдвиньте `observation_end_date` на `2026-06-08`: часть day 7 станет incomplete.
- Добавьте active event без `user_id`: расчет должен остановиться как методологически небезопасный.
- Добавьте active event name, которого нет в tracking plan: activity definition больше не согласована с event model.

## Проверьте это

Запустите тесты:

```bash
python3 -m unittest discover -s tests -v
```

Что проверяется:

- ручные counts tiny-набора;
- совпадение `outputs/cohorts.csv` с пересчетом;
- наличие нулевых complete cells;
- пустой `activity_rate` для incomplete windows;
- исключение test users;
- дедупликация duplicate `event_id`;
- связь active events с tracking plan;
- влияние `observation_end_date`;
- business timezone при назначении cohort date;
- late-arrival policy и CLI failure для invalid spec.

## Поставьте результат

Именованный артефакт:

```text
outputs/cohort_calculator.py
```

Передайте вместе с ним:

- `outputs/cohort_spec.json` - методология;
- `outputs/cohorts.csv` - матрица;
- `cohort-report.json` - quality report конкретного запуска.

Короткое описание для handoff:

```text
cohort_activity_matrix:
cohort_date = registered_at in Europe/Moscow,
unit = user_id,
active events = activity_spec.active_event_names,
age_day = 0..7,
denominator = non-test users in cohort_date,
incomplete windows have blank activity_rate.
```

## Упражнения

1. Измените `observation_end_date` на `2026-06-08` и объясните, какие строки изменили `is_complete_window`.
2. Добавьте cohort dimension `acquisition_channel` в grain и проверьте, как меняется denominator.
3. Добавьте weekly cohort period. Сначала опишите, как должны считаться `cohort_week`, `age_week` и complete windows.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cohort | Любой фильтр пользователей | Группа с общим входным условием и периодом входа |
| Cohort date | Дата события активности | Дата входа пользователя в когорту |
| Age bucket | Номер строки в CSV | Расстояние от cohort date до activity date |
| Cohort size | Число активных в текущей ячейке | Фиксированный denominator исходной когорты |
| Complete window | Ячейка с нулевой активностью | Ячейка, для которой весь период наблюдения уже доступен |
| Incomplete window | Плохая строка данных | Будущая или еще не закрытая ячейка, которую нельзя интерпретировать как ноль |

## Дополнительное чтение

- [Mixpanel Retention](https://docs.mixpanel.com/docs/reports/retention) - официальный разбор retention behavior, cohort buckets и incomplete buckets; полезно перед следующим уроком про возвращаемость.
- [Amplitude: Build a retention analysis](https://amplitude.com/docs/analytics/charts/retention-analysis/retention-analysis-build) - посмотрите, как starting event, return event и user segment превращаются в retention query.
- [Mixpanel Cohorts](https://docs.mixpanel.com/docs/users/cohorts) - про сохраненные пользовательские когорты, shared definitions и verified cohorts; сравните с machine-readable `cohort_spec.json`.
- [Когорты на SQL](../../../04-sql-and-duckdb/09-cohorts/docs/ru.md) - предыдущий урок курса про cohort-period matrix, fixed denominator и полную grid в SQL.
