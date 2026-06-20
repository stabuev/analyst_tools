# Выручка, ARPU и LTV

> Монетизация честна только тогда, когда деньги считаются на платежном grain, а пользовательские метрики делятся на заранее объявленную популяцию и полное окно наблюдения.

**Тип:** Build
**Треки:** Product
**Пререквизиты:** 08-product-analytics/06-retention
**Время:** ~75 минут
**Результат:** вы соберете CLI-калькулятор realized revenue, ARPU, ARPPU и cohort LTV по fixed revenue windows с учетом refunds, pending orders, cancellations и риска many-to-many joins.

## Цели обучения

- Считать выручку на grain `order_id`, не размножая ее join-ами с событиями и подписками.
- Различать gross revenue, refund amount и realized revenue.
- Считать ARPU, ARPPU и fixed-window LTV на фиксированной когорте пользователей.
- Не интерпретировать неполные LTV-окна как нулевую монетизацию.
- Проверять статусы заказов, валюту, суммы, пользователей, подписки и дубликаты перед расчетом.

## Проблема

После retention команда спрашивает: "Ок, пользователи возвращаются плохо или хорошо, но сколько денег это приносит?" На этом этапе легко получить красивую, но неверную таблицу.

Типовая ошибка - соединить `events`, `subscriptions` и `orders` в одну широкую таблицу и просуммировать `amount_rub`. Если у пользователя несколько событий и несколько подписочных периодов, один платеж размножается. Выручка растет не потому, что продукт заработал больше, а потому что join изменил grain.

Вторая ошибка - считать все статусы одинаково. `paid` является realized revenue, `refunded` должен показать возврат и не оставлять выручку в метрике, `pending` еще не деньги. Отмена подписки сама по себе не обязана обнулять уже реализованную выручку, но является важным lifecycle-сигналом.

Третья ошибка знакома по retention: D7 LTV новой когорты нельзя считать, если с даты регистрации еще не прошло семь дней наблюдения. Пустое значение в таком окне честнее, чем `0.00`.

## Концепция

В уроке используются три источника:

```text
users           -> cohort_date and denominator
orders          -> revenue source at order_id grain
subscriptions   -> subscription lifecycle, trial and cancellations
```

Методология в `outputs/monetization_spec.json`:

```text
cohort_date = date(registered_at in Europe/Moscow)
revenue_windows_days = 0, 7
paid status = paid
refund status = refunded
pending status = pending
denominator = non-test users in cohort_date
complete window if cohort_date + window_days <= observation_end_date
```

Денежные поля:

| Поле | Формула |
|---|---|
| `gross_revenue_rub` | сумма `amount_rub` по `paid` и `refunded` заказам в окне |
| `refund_amount_rub` | сумма `amount_rub` по `refunded` заказам в окне |
| `realized_revenue_rub` | `gross_revenue_rub - refund_amount_rub` |
| `arpu_rub` | `realized_revenue_rub / cohort_size` |
| `arppu_rub` | `realized_revenue_rub / paying_users` |
| `ltv_rub` | fixed-window cohort LTV, здесь равен `realized_revenue_rub / cohort_size` |

ARPU и LTV выглядят одинаково в одной строке, потому что обе метрики отвечают на вопрос "сколько realized revenue принес средний пользователь этой когорты за фиксированное окно". Разница в использовании: ARPU часто смотрят по периоду как операционную метрику, а cohort LTV сравнивает накопленную выручку когорт на одинаковом возрасте.

Минимальный pipeline:

```text
users + orders + subscriptions + monetization_spec
  -> validate spec, columns, statuses, currency and money values
  -> deduplicate orders by order_id and subscriptions by subscription_id
  -> exclude test users
  -> assign cohort_date from registered_at
  -> build cohort_date x revenue_window grid
  -> count paid/refunded/pending orders at order_id grain
  -> count subscription starts and cancellations separately
  -> blank money metrics for incomplete windows
  -> emit monetization.csv and quality report
```

## Соберите это

Проверьте одну строку руками. В когорте `2026-06-01` два non-test пользователя: `U001` и `U002`. Оба имеют paid orders в день регистрации:

```python
cohort_size = 2
realized_revenue_rub = 990 + 1490
arpu_rub = realized_revenue_rub / cohort_size  # 1240.00
arppu_rub = realized_revenue_rub / 2           # 1240.00
ltv_rub = arpu_rub                            # fixed D0 cohort LTV
```

Запустите пример:

```bash
python3 code/main.py
```

Он печатает ручной расчет и три контрольные строки:

```json
{
  "manual_2026_06_01_day_0": {
    "cohort_size": "2",
    "paying_users": "2",
    "realized_revenue_rub": "2480.00",
    "arpu_rub": "1240.00"
  },
  "cohort_2026_06_04_day_0_refund": {
    "refunded_orders": "1",
    "gross_revenue_rub": "1490.00",
    "refund_amount_rub": "1490.00",
    "realized_revenue_rub": "0.00"
  },
  "cohort_2026_06_03_day_7_incomplete": {
    "realized_revenue_rub": "",
    "ltv_rub": "",
    "is_complete_window": "false"
  }
}
```

## Используйте это

Рабочий артефакт:

```text
outputs/monetization_calculator.py
```

Запуск из корня урока:

```bash
python3 outputs/monetization_calculator.py \
  --users ../data/tiny/users.csv \
  --orders ../data/tiny/orders.csv \
  --subscriptions ../data/tiny/subscriptions.csv \
  --spec outputs/monetization_spec.json \
  --output monetization.csv \
  --report monetization-report.json
```

Фрагмент результата:

```csv
metric_id,cohort_date,window_days,cohort_size,paying_users,realized_revenue_rub,arpu_rub,arppu_rub,ltv_rub,is_complete_window
cohort_monetization,2026-06-01,0,2,2,2480.00,1240.00,1240.00,1240.00,true
cohort_monetization,2026-06-04,0,1,0,0.00,0.00,0.00,0.00,true
cohort_monetization,2026-06-03,7,1,0,,,,false
```

Baseline `outputs/monetization.csv` содержит 12 строк:

- 6 registered cohorts;
- 2 fixed windows: D0 и D7;
- 8 complete windows;
- 4 incomplete windows.

`monetization-report.json` считается частью поставки. Если report invalid, CSV нельзя использовать в рекомендации, даже если часть строк выглядит правдоподобно.

## Сломайте это

Проверьте типовые ошибки:

- Продублируйте `order_id=O004`: report должен стать invalid, а realized revenue когорты `2026-06-05` не должен удвоиться.
- Продублируйте `subscription_id=SUB003`: report должен стать invalid, а cancellation count не должен удвоиться.
- Добавьте paid order с валютой `USD`: расчет должен остановиться, потому что `revenue_currency` в spec равен `RUB`.
- Сделайте `amount_rub=-10.00`: отрицательная сумма без явной refund-модели запрещена.
- Добавьте второй subscription period для `U001`: `subscriptions_started` изменится, но `realized_revenue_rub` не должен вырасти.
- Сдвиньте `observation_end_date` на `2026-06-12`: D7 для когорты `2026-06-04` станет complete и покажет refund/cancellation.

## Проверьте это

Запустите тесты:

```bash
python3 -m unittest discover -s tests -v
```

Что проверяется:

- полный grid `cohort_date x revenue_window`;
- совпадение `outputs/monetization.csv` с пересчетом;
- paid/refunded/pending order semantics;
- пустые money metrics для incomplete LTV windows;
- cancellation count только в complete window;
- дедупликация `order_id` и `subscription_id`;
- известные users, валюта и неотрицательные суммы;
- валидность revenue windows;
- business timezone для cohort date и revenue window;
- защита от размножения выручки подписочными join-ами;
- CLI failure для invalid spec.

## Поставьте результат

Именованный артефакт:

```text
outputs/monetization_calculator.py
```

Передайте вместе с ним:

- `outputs/monetization_spec.json` - методология монетизации;
- `outputs/monetization.csv` - baseline таблица для tiny-данных;
- `monetization-report.json` - quality report конкретного запуска.

Короткое описание для handoff:

```text
cohort_monetization:
cohort_date = registered_at in Europe/Moscow,
unit = user_id,
revenue source = orders at order_id grain,
paid/refunded/pending statuses are explicit,
subscriptions are lifecycle signals, not revenue multipliers,
windows = D0 and D7,
incomplete windows have blank money metrics.
```

## Упражнения

1. Добавьте paid order для `U003` на D7 и объясните, почему D7 для когорты `2026-06-02` complete, а для `2026-06-03` еще нет.
2. Добавьте статус `chargeback` в orders и расширьте spec так, чтобы он вел себя как refund.
3. Добавьте dimension `acquisition_channel`: сначала опишите denominator, потом посчитайте ARPU по каналам без post-hoc выбора лучшего сегмента.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Revenue grain | Пользователь или событие оплаты | Единица денежного факта, здесь `order_id` |
| Gross revenue | Деньги, которые можно сразу использовать как ARPU | Сумма оплаченных и затем возвращенных заказов до вычитания refunds |
| Realized revenue | Все заказы, включая pending | Деньги, оставшиеся после учета финального статуса заказа |
| ARPU | Выручка на платящего пользователя | `realized_revenue / all eligible users` |
| ARPPU | То же самое, что ARPU | `realized_revenue / paying users` |
| Cohort LTV | Прогноз пожизненной ценности | Наблюдаемая накопленная выручка когорты за фиксированное окно в этом уроке |
| Incomplete LTV window | Нулевая монетизация | Окно, где еще не прошел весь revenue horizon |
| Many-to-many revenue join | Безобидный способ собрать контекст | Join, который размножает платежи и завышает выручку |

## Дополнительное чтение

- [Retention и возвращаемость](../../06-retention/docs/ru.md) - предыдущий урок про fixed cohort denominator и complete-window policy.
- [Mixpanel: Building Revenue Metrics](https://docs.mixpanel.com/docs/features/revenue-analytics) - официальный разбор revenue analytics, ARPU/LTV, refunds, chargebacks, cancellations и recurring revenue.
- [Mixpanel Insights measurements](https://docs.mixpanel.com/docs/reports/insights) - прочитайте раздел `Measurements`: aggregate property и aggregate property per user объясняют разницу суммы и per-user метрик.
- [Google Analytics: Measure ecommerce](https://developers.google.com/analytics/devguides/collection/ga4/ecommerce) - посмотрите, как purchase/refund events требуют transaction id, currency и value для корректной revenue-модели.
