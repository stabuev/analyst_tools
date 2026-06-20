# Воронки и неоднозначность конверсии

> Воронка не отвечает на вопрос "какая конверсия?", пока вы не зафиксировали unit, стартовую популяцию, порядок шагов и окно конверсии.

**Тип:** Build
**Треки:** Product
**Пререквизиты:** 08-product-analytics/03-activity
**Время:** ~75 минут
**Результат:** вы соберете CLI-калькулятор closed funnels и проверите, как меняется ответ при другой единице подсчета и другом порядке шагов.

## Цели обучения

- Описывать продуктовую воронку через первый шаг, unit, ordering и conversion window.
- Считать step conversion и dropoff без смешивания пользователей, сессий и user-days.
- Отлавливать failure modes: duplicate delivery, late arrivals, неизвестные события и неверный порядок шагов.

## Проблема

Команда смотрит на paywall и говорит: "конверсия в trial равна 50%". Это звучит уверенно, но число пока не имеет методологии.

50% от кого? От всех новых пользователей, от тех, кто увидел paywall, от сессий или от user-days? Trial должен случиться строго после paywall или достаточно, что оба события были у пользователя? Сколько ждать trial: 10 минут, 7 дней, месяц? Что делать, если событие пришло поздно или было доставлено дважды?

На tiny product log из этой фазы для воронки `paywall_viewed -> trial_started` есть 4 non-test пользователя, которые увидели paywall: `U001`, `U002`, `U005`, `U007`. Trial после paywall есть у `U001` и `U007`. Поэтому closed user funnel с strict order и окном 7 дней дает 2 из 4, то есть 50%. Другие правила могут дать другое число.

## Концепция

Воронка превращает поток событий в последовательность шагов для одной единицы подсчета.

Ключевые настройки:

- `entry_policy`: в этом уроке используется `closed`, то есть denominator первого шага формируют только единицы, у которых был первый шаг воронки.
- `unit`: граница склейки шагов. `user_id` отвечает на вопрос про пользователей, `session_id` про сессии, `user_day` про пользователя в конкретный календарный день.
- `ordering`: `strict` требует шаги в заданном порядке; `loose` допускает любой порядок, если все шаги есть в окне.
- `conversion_window_minutes`: максимальный лаг от первого найденного шага до последнего засчитанного шага.
- `business_timezone`: календарные границы для `user_day`.
- `exclude_test_users`: тестовые пользователи не должны попадать в denominator.

Минимальная схема расчета:

```text
events + users + tracking_plan + funnel_spec
  -> validate spec and input quality
  -> remove duplicate event_id for calculation
  -> exclude test users
  -> group step events by unit
  -> match strict or loose step sequence inside conversion window
  -> emit funnel.csv with units, conversion and dropoff
```

Главная ловушка: воронка не обязана быть "пользовательской". Один и тот же `trial_started` может считаться конверсией в user funnel и не считаться в session funnel, если paywall был в другой сессии.

## Соберите это

Начните с прозрачного ручного расчета для самой короткой воронки:

```python
paywall_users = users_with("paywall_viewed")
trial_users = users_with("trial_started after paywall_viewed")
conversion = len(trial_users) / len(paywall_users)
```

В уроке это вынесено в `code/main.py`. Запустите из папки урока:

```bash
python3 code/main.py
```

Скрипт печатает ручной baseline и результат общего калькулятора:

```json
{
  "manual_paywall_to_trial": {
    "paywall_users": 4,
    "trial_users_after_paywall": 2,
    "conversion": 0.5
  },
  "valid": true
}
```

Ручная функция полезна как контрольная точка, но быстро ломается при новых правилах: session scope, loose ordering, late arrivals, дедупликация и несколько воронок требуют общего spec-driven расчета.

## Используйте это

Рабочий артефакт урока: `outputs/funnel_calculator.py`. Он принимает четыре источника:

- `events.csv`: поток событий;
- `users.csv`: популяция и test-user flag;
- `tracking_plan.json`: допустимые события и политика late arrivals;
- `funnel_spec.json`: методология воронок.

Запуск:

```bash
python3 outputs/funnel_calculator.py \
  --events ../data/tiny/events.csv \
  --users ../data/tiny/users.csv \
  --tracking-plan ../02-event-model/outputs/tracking_plan.json \
  --spec outputs/funnel_spec.json \
  --output outputs/funnel.csv \
  --report funnel-report.json
```

Фрагмент результата:

```csv
funnel_id,step_id,units,conversion_from_start,dropoff_from_previous
paywall_trial_user_strict_7d,paywall_viewed,4,1.000000,0
paywall_trial_user_strict_7d,trial_started,2,0.500000,2
```

`funnel-report.json` показывает, прошли ли проверки качества: обязательные колонки, уникальность `event_id`, существование step events в tracking plan, поддерживаемые units, timezone-aware timestamps и соблюдение late-arrival policy.

## Сломайте это

Проверьте спорные случаи до того, как число попадет в презентацию:

- Duplicate delivery: повторите `event_id=E038`. Report станет invalid, но расчет после дедупликации останется 2 trials.
- Out-of-order: добавьте пользователя, у которого `trial_started` был до `paywall_viewed`. Strict funnel не засчитает конверсию, loose funnel засчитает.
- Cross-session: добавьте `trial_started` для `U005` в новой сессии. User funnel засчитает, session funnel нет.
- Cross-day: добавьте `trial_started` на следующий день. User funnel засчитает, user-day funnel нет.
- Unknown event: замените шаг на событие, которого нет в tracking plan. Калькулятор не должен строить CSV как будто все хорошо.
- Late arrival: сдвиньте `received_at` дальше допустимого окна из tracking plan. Report должен показать нарушение.

## Проверьте это

Запустите behavioral tests:

```bash
python3 -m unittest discover -s tests -v
```

Что они защищают:

- эталонные counts для activation и paywall funnels;
- совпадение `outputs/funnel.csv` с пересчитанной таблицей;
- дедупликацию duplicate `event_id`;
- ошибки в funnel spec;
- strict versus loose order;
- изоляцию `session_id` и `user_day`;
- late-arrival quality check;
- CLI contract: valid spec возвращает `0`, invalid spec возвращает `1`.

## Поставьте результат

Именованный артефакт:

```text
outputs/funnel_calculator.py
```

Повторное использование:

```bash
python3 outputs/funnel_calculator.py \
  --events path/to/events.csv \
  --users path/to/users.csv \
  --tracking-plan path/to/tracking_plan.json \
  --spec path/to/funnel_spec.json \
  --output path/to/funnel.csv \
  --report path/to/funnel-report.json
```

Перед тем как отдавать число заказчику, приложите к нему методологию:

```text
paywall_to_trial_conversion_7d = closed strict user funnel,
unit=user_id,
first_step=paywall_viewed,
last_step=trial_started,
window=7 days,
test users excluded,
duplicate event_id deduplicated and reported.
```

## Упражнения

1. Добавьте в `funnel_spec.json` воронку `signup_started -> account_created -> onboarding_completed` и проверьте, где возникает главный dropoff.
2. Сравните `paywall_trial` для `user_id`, `session_id` и `user_day`. Объясните, какой вариант подходит для продуктового решения о paywall.
3. Добавьте настройку `exact` ordering: между шагами не должно быть других funnel-step событий. Напишите тест, где strict засчитывает, а exact не засчитывает.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Closed funnel | Denominator можно брать из всех пользователей продукта | Denominator первого шага состоит из единиц, реально вошедших в первый шаг |
| Unit | `user_id`, `session_id` и `user_day` взаимозаменяемы | Unit задает границу, внутри которой склеиваются шаги |
| Strict ordering | Порядок строк в CSV должен совпадать с порядком шагов | Порядок определяется `occurred_at`, а не физическим порядком строк |
| Loose ordering | Можно засчитать неполную последовательность | Шаги могут быть в любом порядке, но все засчитанные шаги должны существовать в окне |
| Conversion window | Просто фильтр по дате отчета | Максимальный допустимый лаг от первого шага до последующих шагов |

## Дополнительное чтение

- [Mixpanel Funnels overview](https://docs.mixpanel.com/docs/reports/funnels/funnels-overview) - официальный обзор воронок: посмотрите, как продуктовые инструменты связывают conversion с events и conversion window.
- [Amplitude: Build a funnel analysis](https://amplitude.com/docs/analytics/charts/funnel-analysis/funnel-analysis-build) - настройки порядка шагов, exclusion и анализа funnel paths; полезно сравнить с `strict` и `loose` в этом уроке.
- [Google Analytics 4: Funnel explorations](https://support.google.com/analytics/answer/9327974) - официальный пример open/closed funnels, directly/indirectly followed by и timeframe.
- [Активность и активная аудитория](../../03-activity/docs/ru.md) - предыдущий урок курса про eligible population, business timezone и неполные окна наблюдения.
