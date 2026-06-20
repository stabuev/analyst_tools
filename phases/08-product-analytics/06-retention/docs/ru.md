# Retention и возвращаемость

> Retention показывает не "сколько было активности", а какая доля исходной когорты вернулась в продукт после старта при полностью наблюдаемом окне.

**Тип:** Build
**Треки:** Product
**Пререквизиты:** 08-product-analytics/05-cohorts
**Время:** ~75 минут
**Результат:** вы соберете CLI-калькулятор daily retention с режимами `exact_day` и `on_or_after`, фиксированным denominator и явной политикой incomplete windows.

## Цели обучения

- Отличать старт когорты от return behavior и не считать day 0 возвращением.
- Считать retention на фиксированном `cohort_size`, а не на числе активных пользователей текущего дня.
- Различать `exact_day` и `on_or_after` retention.
- Помечать неполные окна наблюдения и не заполнять их нулями.
- Проверять tracking plan, activity spec, duplicate delivery, identity и late arrivals перед расчетом.

## Проблема

Команда видит, что новые пользователи проходят onboarding и совершают активные события в день регистрации. Следующий вопрос звучит просто: "они возвращаются?"

На этом месте легко сделать две ошибки.

Первая ошибка - принять стартовую активность за retention. Если пользователь зарегистрировался 1 июня и в тот же день открыл приложение, это подтверждает day 0 activity, но не возвращение. Retention начинается после старта, когда есть шанс уйти и вернуться.

Вторая ошибка - записать `0%` там, где окно еще не наблюдалось. В tiny-логе последняя дата события - `2026-06-09`. Для когорты `2026-06-03` `exact_day` на day 1 уже завершен, а `on_or_after` day 1 смотрит весь интервал `2026-06-04..2026-06-10`. Такой интервал еще не закрыт, поэтому rate должен быть пустым, а не нулевым.

В этом уроке вы строите retention так, чтобы таблицу можно было безопасно использовать в финальном продуктово-аналитическом расследовании: с машинной спецификацией, полным grid, quality report и тестами на failure modes.

## Концепция

Retention состоит из четырех решений:

```text
start_source = registered_at
cohort_date = date(registered_at in Europe/Moscow)
return_event_names = active_event_names from activity_spec
denominator = count(non-test users in cohort_date)
```

В этой фазе retention считается по зарегистрированным пользователям, а return events берутся из определения активности:

```text
app_open
feature_value_seen
paywall_viewed
trial_started
subscription_started
order_paid
support_ticket_created
```

Day 0 исключен:

```text
count_start_day_as_return = false
age_days = 1..7
```

Два режима отвечают на разные вопросы:

| Режим | Окно | Вопрос |
|---|---|---|
| `exact_day` | ровно `cohort_date + age_day` | "Какая доля когорты вернулась именно на N-й день?" |
| `on_or_after` | `cohort_date + age_day .. cohort_date + max_age_day` | "Какая доля когорты вернулась хотя бы один раз начиная с N-го дня до конца горизонта?" |

Пример для когорты `2026-06-01`, `max_age_day=7`:

```text
exact_day, age_day=2      -> 2026-06-03
on_or_after, age_day=2    -> 2026-06-03..2026-06-08
```

Complete-window policy:

```text
exact_day complete      if cohort_date + age_day <= observation_end_date
on_or_after complete    if cohort_date + max_age_day <= observation_end_date
incomplete rate         = blank
```

Почему для `on_or_after` нужен полный горизонт? Если вы смотрите "вернулся начиная с day 1 до day 7", нельзя честно посчитать долю до того, как наступил day 7. Иначе новые когорты будут выглядеть хуже старых просто потому, что им дали меньше времени.

Минимальный pipeline:

```text
users + events + tracking_plan + activity_spec + retention_spec
  -> validate spec, active return events and timestamps
  -> deduplicate events by event_id
  -> exclude test users
  -> assign cohort_date from registered_at
  -> build cohort_date x retention_mode x age_day grid
  -> mark complete windows against observation_end_date
  -> count distinct retained users and return event counts
  -> emit retention.csv and quality report
```

## Соберите это

Сначала проверьте одну ячейку руками. В когорте `2026-06-01` два non-test пользователя: `U001` и `U002`.

```python
cohort_size = 2
retained_users_day_1_exact = 0
retention_rate = retained_users_day_1_exact / cohort_size  # 0.0
```

Почему ноль корректен? Day 1 для этой когорты - `2026-06-02`, эта дата уже есть в наблюдении, и у `U001`/`U002` нет return events в этот день. Это наблюдаемый ноль.

Запустите пример:

```bash
python3 code/main.py
```

Он печатает ручной расчет и две контрольные строки:

```json
{
  "manual_2026_06_01_day_1_exact": {
    "cohort_size": 2,
    "retained_users": 0,
    "retention_rate": 0.0
  },
  "exact_day_2026_06_01_day_1": {
    "retention_mode": "exact_day",
    "cohort_date": "2026-06-01",
    "age_day": "1",
    "retention_rate": "0.000000",
    "is_complete_window": "true"
  },
  "on_or_after_2026_06_03_day_1": {
    "retention_mode": "on_or_after",
    "cohort_date": "2026-06-03",
    "age_day": "1",
    "retention_rate": "",
    "is_complete_window": "false"
  }
}
```

Главная мысль: одинаковый `age_day=1` может быть complete для `exact_day` и incomplete для `on_or_after`, потому что окна разные.

## Используйте это

Рабочий артефакт:

```text
outputs/retention_calculator.py
```

Запуск из корня урока:

```bash
python3 outputs/retention_calculator.py \
  --events ../data/tiny/events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --activity-spec ../03-activity/outputs/activity_spec.json \
  --spec outputs/retention_spec.json \
  --output retention.csv \
  --report retention-report.json
```

Фрагмент результата:

```csv
metric_id,retention_mode,cohort_date,age_day,return_window_start,return_window_end,cohort_size,retained_users,retention_rate,is_complete_window,return_event_count
active_retention,exact_day,2026-06-01,1,2026-06-02,2026-06-02,2,0,0.000000,true,0
active_retention,on_or_after,2026-06-01,1,2026-06-02,2026-06-08,2,0,0.000000,true,0
active_retention,on_or_after,2026-06-03,1,2026-06-04,2026-06-10,1,0,,false,0
```

Baseline `outputs/retention.csv` содержит 84 строки:

- 6 registered cohorts;
- 2 retention modes;
- 7 возрастов `age_day=1..7`;
- 44 complete windows;
- 40 incomplete windows.

Report считается частью результата. Если он invalid, таблица не готова для handoff, даже если CSV технически записался.

## Сломайте это

Проверьте типовые поломки:

- Добавьте return event для `U001` на `2026-06-03`: `exact_day` day 2 станет `0.500000`, а `on_or_after` day 1 для когорты `2026-06-01` увидит этого пользователя во всем последующем окне.
- Добавьте второе return event для `U002` на day 5: `on_or_after` day 1 удержит двух пользователей, но `exact_day` day 2 и day 5 покажут разные ячейки.
- Продублируйте `event_id`: report должен стать invalid, а retained users и event count не должны удвоиться после дедупликации.
- Добавьте return event без `user_id`: расчет методологически небезопасен, потому что retention считается по пользователям.
- Добавьте return event name, которого нет в `activity_spec` или tracking plan: определение возвращения разъехалось с продуктовой моделью.
- Сдвиньте `observation_end_date` назад: часть строк должна стать incomplete и получить пустой `retention_rate`.

## Проверьте это

Запустите тесты:

```bash
python3 -m unittest discover -s tests -v
```

Что проверяется:

- полный grid `cohort_date x retention_mode x age_day`;
- совпадение `outputs/retention.csv` с пересчетом;
- day 0 activity не считается возвращением;
- разные semantics `exact_day` и `on_or_after`;
- пустой rate для incomplete windows;
- дедупликация duplicate `event_id`;
- запрет return events без `user_id`;
- связь return events с `activity_spec` и tracking plan;
- непрерывность `age_days` от 1;
- валидность retention modes;
- влияние `observation_end_date`;
- business timezone при назначении cohort date;
- late-arrival policy и CLI failure для invalid spec.

## Поставьте результат

Именованный артефакт:

```text
outputs/retention_calculator.py
```

Передайте вместе с ним:

- `outputs/retention_spec.json` - методология retention;
- `outputs/retention.csv` - baseline таблица для tiny-данных;
- `retention-report.json` - quality report конкретного запуска.

Короткое описание для handoff:

```text
active_retention:
cohort_date = registered_at in Europe/Moscow,
unit = user_id,
return events = active_event_names from activity_spec,
age_day = 1..7,
modes = exact_day and on_or_after,
denominator = non-test users in cohort_date,
incomplete windows have blank retention_rate.
```

## Упражнения

1. Добавьте return event для `U001` на day 2 и объясните, какие строки изменились в `exact_day` и `on_or_after`.
2. Поменяйте `observation_end_date` на `2026-06-08` и перечислите строки, которые стали incomplete.
3. Добавьте отдельный return event set только из `app_open` и сравните retention с более широким active return definition.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Retention | Любая активность пользователей | Доля исходной когорты, совершившая return behavior после стартового условия |
| Return event | Первое событие пользователя в продукте | Событие, которое заранее признано осмысленным возвращением |
| Exact-day retention | Retention за все дни после регистрации | Возвращение ровно на указанном `age_day` |
| On-or-after retention | То же самое, что cumulative active users | Возвращение хотя бы один раз в окне от `age_day` до конца горизонта |
| Denominator | Число активных пользователей в окне | Фиксированный размер исходной когорты |
| Incomplete window | Нулевая возвращаемость | Окно, для которого еще нет полного периода наблюдения |

## Дополнительное чтение

- [Когортный анализ](../../05-cohorts/docs/ru.md) - предыдущий урок, где фиксируются cohort date, denominator и complete-window policy.
- [Mixpanel Retention](https://docs.mixpanel.com/docs/reports/retention) - официальный разбор retention behavior, режимов "on" / "on or after" и неполных buckets.
- [Amplitude: Build a retention analysis](https://amplitude.com/docs/analytics/charts/retention-analysis/retention-analysis-build) - посмотрите, как starting event, return event и user segment задают retention query.
- [Amplitude: How retention is calculated](https://amplitude.com/docs/analytics/charts/retention-analysis/retention-analysis-calculation) - детали расчета retention и интерпретации периодов.
