# Активность и активная аудитория

> Active user - это не пользователь с любым событием, а пользователь с заранее
> определенным значимым действием в заданном окне.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 08/02 - Событийная модель продукта  
**Время:** ~75 минут  
**Результат:** считает DAU/rolling active users по явному набору активных событий, grain
`user_id`, eligible population, business timezone и окнам 1/7 дней, исключая test users и
помечая неполные окна.

## Цели обучения

- Задавать active audience через `grain`, `active_event_names`, `window` и population.
- Отличать active users от total users, new users и количества событий.
- Строить полный календарный ряд, включая дни без активности.
- Исключать test users и дедуплицировать повторную доставку событий.
- Помечать неполные rolling windows, чтобы не сравнивать их с полными окнами.

## Проблема

После изменения onboarding команда видит:

```text
signup_started вырос
account_created вырос
```

Можно поспешить и сказать:

```text
Активная аудитория выросла.
```

Это опасно. Регистрация - не обязательно активность. Пользователь мог создать аккаунт,
застрять в onboarding и не увидеть ценность продукта. Еще хуже, если в DAU попали test
users или дубликаты событий: тогда рост активной аудитории может оказаться ростом
трекинга, а не продукта.

Нужно заранее ответить:

```text
Кто считается eligible?
Что значит active?
За какой window считаем?
В какой business timezone строим день?
Что делаем с неполными окнами?
```

## Концепция

### Active audience - это спецификация

В этом уроке active audience задана в `outputs/activity_spec.json`:

```json
{
  "grain": "user_id",
  "active_event_names": [
    "app_open",
    "feature_value_seen",
    "paywall_viewed",
    "trial_started",
    "subscription_started",
    "order_paid",
    "support_ticket_created"
  ],
  "windows_days": [1, 7],
  "business_timezone": "Europe/Moscow",
  "exclude_test_users": true
}
```

Мы сознательно не считаем `signup_started` и `account_created` активностью. Они важны для
воронок, но сами по себе не доказывают, что пользователь использовал продукт.
`subscription_cancelled` тоже не входит в active events: это guardrail-сигнал, а не
здоровая активность.

### Числитель и знаменатель

Для каждой даты:

```text
active_users = unique user_id с active event в окне
eligible_users = зарегистрированные non-test users на конец даты
activity_rate = active_users / eligible_users
```

Если забыть denominator, DAU станет просто числом людей. Это полезно для capacity
planning, но плохо отвечает на вопрос "какая доля доступной аудитории была активна".

### Rolling window не всегда полон

Для 7-дневного окна дата `2026-06-03` в tiny-профиле использует только историю с
`2026-06-01` по `2026-06-03`. Это не честное 7-дневное окно, поэтому в `activity.csv`
строка помечается:

```text
is_complete_window=false
```

Сравнивать такую строку с `2026-06-09`, где есть полный lookback, нельзя без оговорки.

### Business date зависит от timezone

Событие `2026-06-01T22:30:00+00:00` попадает в `2026-06-02` для `Europe/Moscow`. Поэтому
activity date нельзя брать простым `occurred_at[:10]`, если в логе смешаны offset-ы.

## Соберите это

Откройте `code/main.py`. Минимальная ручная версия считает active users только по датам,
которые встретились в active events:

```python
def manual_daily_active_users(events: list[dict[str, str]], active_names: set[str]) -> dict[str, int]:
    users_by_date: dict[str, set[str]] = {}
    for row in events:
        if row["event_name"] not in active_names:
            continue
        activity_date = row["occurred_at"][:10]
        users_by_date.setdefault(activity_date, set()).add(row["user_id"])
    return {day: len(users) for day, users in sorted(users_by_date.items())}
```

Запустите:

```bash
uv run --locked python code/main.py
```

Вы увидите:

```json
{
  "calculator_summary": {
    "rows": 18,
    "eligible_users": 7,
    "windows_days": [1, 7]
  },
  "valid": true
}
```

Ручная версия полезна для интуиции, но в ней есть дырки: она не создает строки для дней
без активности, не помечает неполные rolling windows и не проверяет denominator.

### Шаг 1: объявите active events

Не используйте "любое событие" как activity definition. В нашем продукте осмысленная
активность:

```text
app_open
feature_value_seen
paywall_viewed
trial_started
subscription_started
order_paid
support_ticket_created
```

Список должен существовать в tracking plan из `08/02`.

### Шаг 2: соберите eligible population

Для каждого дня берем зарегистрированных non-test users:

```text
registered_at <= activity_date end
is_test_user = false
```

Так denominator растет по мере появления новых пользователей. `U999` из tiny-профиля
явно исключается как test user.

### Шаг 3: дедуплицируйте события

Повторная доставка одного `event_id` не должна увеличивать `active_event_count`. Для
`active_users` дубликат часто не меняет unique count, но все равно портит диагностику
интенсивности и качество входа.

### Шаг 4: постройте полный календарь

Даже если `2026-06-06` не содержит active events, строка нужна:

```csv
2026-06-06,1,true,6,0,0.000000,0
```

Иначе график silently пропустит нулевые дни и станет слишком оптимистичным.

## Используйте это

Артефакт урока:

```text
outputs/activity_calculator.py
```

Запуск из папки урока:

```bash
uv run --locked python outputs/activity_calculator.py \
  --events ../data/tiny/events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --spec outputs/activity_spec.json \
  --output activity.csv \
  --report activity-report.json
```

Фрагмент `outputs/activity.csv`:

```csv
activity_date,window_days,is_complete_window,eligible_users,active_users,activity_rate,active_event_count
2026-06-01,1,true,2,2,1.000000,6
2026-06-07,7,true,6,5,0.833333,12
2026-06-09,7,true,7,3,0.428571,8
```

Quality report проверяет:

1. activity spec содержит обязательные поля;
2. active events существуют в tracking plan;
3. `windows_days` - положительные целые числа;
4. grain равен `user_id`;
5. business timezone является IANA timezone;
6. в `events` и `users` есть обязательные колонки;
7. `event_id` и `user_id` уникальны;
8. active events имеют `user_id` и ссылаются на известных users;
9. active event timestamps timezone-aware;
10. activity table содержит строки.

Для учебного просмотра invalid report:

```bash
uv run --locked python outputs/activity_calculator.py \
  --events broken-events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --spec outputs/activity_spec.json \
  --output activity.csv \
  --allow-failures
```

## Сломайте это

Попробуйте по одному дефекту:

1. Добавьте в `active_event_names` событие `daily_active_user` - должен упасть
   `active_events_in_tracking_plan`.
2. Поставьте `windows_days: [1, 0]` - должен упасть `activity_windows_positive`.
3. Очистите `user_id` у `feature_value_seen` - должен упасть
   `active_events_have_user_id`.
4. Добавьте дубликат `event_id=E031` - должен упасть `event_ids_unique`, а
   `active_event_count` за `2026-06-05` не должен вырасти.
5. Добавьте active event для `U999` - denominator и activity не должны измениться,
   потому что пользователь тестовый.
6. Добавьте событие около полуночи в UTC - проверьте, в какую дату оно попадет в
   `Europe/Moscow`.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- tiny-profile дает 18 строк: 9 дат на окна 1 и 7 дней;
- `outputs/activity.csv` совпадает с расчетом;
- дни без active events сохраняются;
- первые 7-дневные окна помечены как неполные;
- test users не попадают в denominator и activity;
- duplicate delivery не раздувает `active_event_count`;
- active event без `user_id` отклоняется;
- active events обязаны существовать в tracking plan;
- нулевой window отклоняется;
- timezone меняет activity date;
- CLI пишет CSV и report;
- CLI возвращает `1` для invalid activity spec.

Проверка данных фазы:

```bash
uv run --locked python ../data/generate_data.py --check
```

## Поставьте результат

Передавайте:

```text
outputs/activity_calculator.py
outputs/activity_spec.json
outputs/activity.csv
activity-report.json
```

Минимальная поставка:

```bash
uv run --locked python outputs/activity_calculator.py \
  --events ../data/tiny/events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --spec outputs/activity_spec.json \
  --output activity.csv \
  --report activity-report.json
```

В следующих уроках `activity.csv` станет контекстом для funnel, cohort и retention:
если активная аудитория падает или окно неполное, конверсию и возвращаемость нельзя
интерпретировать как чистый продуктовый сигнал.

## Упражнения

1. Добавьте отдельный расчет active users только по `feature_value_seen` и сравните его с
   текущим broad activity definition.
2. Добавьте окно `28` дней. Какие строки будут неполными в tiny-профиле?
3. Добавьте dimension `platform` и объясните, почему denominator должен считаться по
   пользователям этой platform, а не по всем пользователям сразу.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Active user | Любой пользователь с любым событием | Пользователь, совершивший заранее объявленное значимое действие в заданном окне |
| DAU | Просто количество событий за день | Unique users с active event в daily window |
| Rolling active users | Скользящая сумма DAU | Unique users, активные хотя бы раз внутри rolling window |
| Eligible population | Все пользователи в таблице `users` | Пользователи, которые уже могли быть активны на дату расчета и не исключены фильтрами |
| Incomplete window | Нормальная первая строка графика | Окно, для которого в данных нет полного lookback, поэтому сравнение ограничено |
| Business timezone | Декоративная настройка отчета | Правило, которое превращает timestamp в product date |

## Дополнительное чтение

- [Google Analytics: Understand user metrics](https://support.google.com/analytics/answer/12253918) - посмотрите различие total users, new users, active users и returning users.
- [Mixpanel: Insights](https://docs.mixpanel.com/docs/reports/insights) - прочитайте, как продуктовые события агрегируются как trends и unique users.
- [Amplitude: Interpret your retention analysis](https://amplitude.com/docs/analytics/charts/retention-analysis/retention-analysis-interpret) - обратите внимание на time frame, timezone и неполные данные в окнах.
- [Урок 08/02: Событийная модель продукта](../../02-event-model/docs/ru.md) - вернитесь к tracking plan, если active events не проходят проверку контракта.
