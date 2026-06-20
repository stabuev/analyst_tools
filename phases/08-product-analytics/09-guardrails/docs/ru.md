# Guardrail-метрики

> Guardrail-метрика не должна украшать отчет. Она должна заранее сказать, когда улучшение outcome слишком дорого для продукта.

**Тип:** Build  
**Треки:** product  
**Пререквизиты:** `08-product-analytics/08-segmentation`  
**Время:** ~75 минут

## Цели обучения

- Описывать guardrail-метрику через grain, numerator, denominator, window и risk direction.
- Считать `support_ticket_rate`, `subscription_cancel_rate` и `refund_rate` с явными thresholds.
- Отличать `breached`, `watch`, `ok` и `incomplete` decision status.
- Не публиковать guardrail rate по неполному observation window.
- Блокировать rollout, если outcome улучшился ценой роста жалоб, отмен или возвратов.

## Проблема

Команда хочет продолжать rollout: activation и paywall conversion выглядят лучше, а сегментация уже подсказала, где искать проблему. Но рядом появляются неприятные сигналы: больше обращений в поддержку, больше отмен подписки, есть refunded order.

Если смотреть только outcome, решение будет простым: "метрика выросла, катим дальше". Это плохая продуктовая дисциплина. Улучшение outcome может быть куплено ухудшением опыта пользователя, ростом нагрузки на поддержку или денежным риском. Поэтому guardrails должны быть частью решения заранее, а не последней строкой в отчете, которую можно проигнорировать.

В этом уроке мы строим CLI-калькулятор guardrail-метрик. Он считает:

- `support_ticket_rate_7d` - доля новых пользователей с обращением в поддержку за 7 дней;
- `subscription_cancel_rate_14d` - доля начавших подписку, отменивших ее за 14 дней;
- `refund_rate_7d` - доля settled orders, которые стали refunded за 7 дней.

Все три риска имеют `risk_direction = up_is_bad`. Если comparison-период превышает threshold или delta слишком большой, rollout блокируется.

## Концепция

Guardrail-метрика похожа на обычную ratio metric, но ее роль другая. Outcome отвечает "достигли ли мы цели?", input-метрики объясняют "какие рычаги сработали?", а guardrails отвечают "не сломали ли мы что-то важное по дороге?".

У guardrail есть пять обязательных частей.

**Grain.** Риск должен считаться на той единице, где он возникает. Support ticket rate считается на `user_id`: пользователь либо создал обращение в окне, либо нет. Cancel rate считается на `subscription_id`: одна подписка может быть отменена. Refund rate считается на `order_id`: возврат относится к заказу, а не к пользователю целиком.

**Window.** Guardrail без окна часто врет. Если subscription cancel rate имеет окно 14 дней, подписка, начатая вчера, еще не успела прожить 14 дней. Ее нельзя считать как "не отменена".

**Risk direction.** Для activation `up` обычно хорошо. Для жалоб, отмен и возвратов рост плохой. Поэтому в спецификации хранится `up_is_bad`, а не молчаливая договоренность в голове аналитика.

**Threshold.** В уроке есть два порога: `max_rate` и `max_delta`. Первый говорит "выше этого абсолютного уровня риск неприемлем", второй - "такой рост относительно baseline неприемлем". Оба порога задаются до просмотра результата.

**Decision status.** Значение метрики само по себе еще не решение. Калькулятор присваивает:

```text
breached   threshold нарушен
watch      риск вырос, но threshold не нарушен
ok         риск не вырос или снизился
incomplete окно наблюдения еще не закрыто
```

На tiny-данных итог суровый: `support_ticket_rate_7d` вырос с `0.250000` до `0.666667`, `subscription_cancel_rate_14d` с `0.000000` до `0.500000`, `refund_rate_7d` с `0.000000` до `0.500000`. Все три guardrails breached, поэтому общий статус - `block_rollout`.

## Соберите это

Артефакт урока находится в `outputs/guardrail_calculator.py`. Он читает:

- `data/tiny/users.csv` - зарегистрированные пользователи и test-user флаг;
- `data/tiny/support_tickets.csv` - обращения в поддержку;
- `data/tiny/subscriptions.csv` - подписки и отмены;
- `data/tiny/orders.csv` - платежи, refunds и pending orders;
- `01-metric-tree/outputs/metric_specs.json` - уже объявленные metric specs;
- `outputs/guardrail_spec.json` - thresholds, windows и risk direction.

Запустите калькулятор из корня репозитория:

```bash
python3 phases/08-product-analytics/09-guardrails/outputs/guardrail_calculator.py \
  --users phases/08-product-analytics/data/tiny/users.csv \
  --support-tickets phases/08-product-analytics/data/tiny/support_tickets.csv \
  --subscriptions phases/08-product-analytics/data/tiny/subscriptions.csv \
  --orders phases/08-product-analytics/data/tiny/orders.csv \
  --metric-specs phases/08-product-analytics/01-metric-tree/outputs/metric_specs.json \
  --spec phases/08-product-analytics/09-guardrails/outputs/guardrail_spec.json \
  --output phases/08-product-analytics/09-guardrails/outputs/guardrails.csv \
  --report /tmp/guardrails-report.json
```

Калькулятор проверяет:

- обязательные колонки во всех входных таблицах;
- уникальность `user_id`, `ticket_id`, `subscription_id`, `order_id`;
- timezone-aware timestamps;
- связи support tickets, subscriptions и orders с известными пользователями;
- что `support_ticket_rate_7d` и `subscription_cancel_rate_14d` есть в metric specs как `role=guardrail`;
- что `risk_direction` совпадает с `expected_direction=up_is_bad`;
- lifecycle подписки: cancelled subscription должна иметь валидный `ended_at`;
- domain для refunds: ожидаемая валюта, допустимые статусы и неотрицательная сумма.

Дубликаты `ticket_id`, `subscription_id` и `order_id` делают quality report невалидным, но расчет строится с дедупликацией. Это помогает увидеть число и одновременно не выдавать грязный batch за чистый.

## Используйте это

`outputs/guardrails.csv` содержит два типа строк:

- `metric` - значение guardrail в `baseline` и `comparison`;
- `assessment` - сравнение baseline/comparison, delta, threshold breach и decision status.

Ключевые строки:

```text
support_ticket_rate_7d        baseline=0.250000 comparison=0.666667 delta=0.416667 breached
subscription_cancel_rate_14d  baseline=0.000000 comparison=0.500000 delta=0.500000 breached
refund_rate_7d                baseline=0.000000 comparison=0.500000 delta=0.500000 breached
```

Сформулируйте вывод так:

```text
Outcome нельзя интерпретировать отдельно от guardrails.
Все три риска имеют risk_direction=up_is_bad и нарушили thresholds.
Рекомендация расчета: block_rollout до разбора support, cancellations и refunds.
```

Запустите пример:

```bash
python3 phases/08-product-analytics/09-guardrails/code/main.py
```

Он печатает ручную сверку `support_ticket_rate_7d`, summary калькулятора и assessment rows для всех трех guardrails.

## Сломайте это

Попробуйте четыре поломки.

1. Поставьте `observation_end_date` в `2026-06-10`. Для comparison-пользователей 7-дневные окна еще не закрыты, а для subscription cancel rate не закрыто и baseline-окно 14 дней. Калькулятор оставит counts/исключения, но очистит rate и вернет `wait_for_complete_windows`.
2. Поменяйте `risk_direction` у `support_ticket_rate_7d` на `down_is_bad`. Spec станет невалидным: этот guardrail должен совпадать с metric specs.
3. Уберите `ended_at` у cancelled subscription. Нельзя считать cancel rate, если lifecycle-сигнал противоречивый.
4. Поменяйте валюту заказа на `USD` или поставьте отрицательную сумму. Refund guardrail должен защищать денежный домен, а не молча считать мусор.

Самая важная поломка - первая. Неполное окно часто выглядит как "все хорошо, жалоб нет". На самом деле это только "мы еще не дождались конца окна".

## Проверьте это

Запустите тесты урока:

```bash
cd phases/08-product-analytics/09-guardrails
python3 -m unittest discover -s tests -v
```

Тесты проверяют:

- tiny-расчет дает 9 строк и `overall_decision=block_rollout`;
- `guardrails.csv` совпадает с расчетом;
- дубликаты tickets/subscriptions/orders репортятся и дедуплицируются;
- unknown `user_id` блокирует расчет;
- cancelled subscription требует `ended_at`;
- refunds проверяют currency/status/amount domain;
- guardrail из metric specs обязан быть `role=guardrail` и `up_is_bad`;
- incomplete windows очищают metric value и переводят decision в ожидание;
- высокие thresholds переводят рост риска в `watch`, а не `breached`;
- timezone `Europe/Moscow` управляет назначением периода;
- test users исключаются из denominator;
- CLI возвращает ненулевой код для невалидной спецификации.

## Поставьте результат

Готовый результат урока:

- `outputs/guardrail_spec.json` - контракт guardrails, thresholds и decision rules;
- `outputs/guardrail_calculator.py` - CLI-калькулятор;
- `outputs/guardrails.csv` - именованный артефакт с metric и assessment rows;
- `outputs/artifact.json` - описание артефакта для индекса курса;
- `tests/test_main.py` - behavioral tests.

Безопасный handoff:

```text
В comparison-периоде все три guardrails breached:
support_ticket_rate_7d = 0.666667, subscription_cancel_rate_14d = 0.500000,
refund_rate_7d = 0.500000. Так как risk_direction=up_is_bad и thresholds нарушены,
rollout нельзя продолжать только на основании outcome. Следующий шаг - investigate
или rollback до раздельного разбора support/cancel/refund причин.
```

Это не causal claim. Это risk decision по заранее объявленным правилам.

## Упражнения

1. Поднимите `max_rate` и `max_delta` до `1.0` и объясните, почему статус становится `watch`, а не `breached`.
2. Добавьте новый support ticket для test user и проверьте, что denominator/numerator не меняются.
3. Сделайте `refund_rate_7d` metric-spec-required и объясните, что придется добавить в metric tree, чтобы spec стал валидным.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Guardrail metric | "Второстепенная метрика для справки" | Метрика риска, которая может ограничить или заблокировать продуктовый rollout |
| Risk direction | "Все метрики хорошо растут" | Правило интерпретации направления: для жалоб, отмен и возвратов рост плохой |
| Threshold | "Порог можно выбрать после результата" | Заранее заданная граница допустимого риска |
| Complete window | "Если события еще не пришли, значит их нет" | Окно наблюдения, которое должно полностью закрыться до публикации rate |
| Breached | "Метрика просто стала хуже" | Guardrail нарушил допустимый абсолютный уровень или delta |
| Watch | "Все нормально" | Риск вырос, но еще не нарушил threshold; нужен мониторинг или разбор |

## Дополнительное чтение

- [Mixpanel Metric Tree](https://docs.mixpanel.com/docs/metric_tree) - посмотрите, как дерево метрик связывает inputs, outputs и контекст решения, чтобы guardrails не жили отдельно от продуктовой цели.
- [Risk-aware product decisions in A/B tests with multiple metrics](https://arxiv.org/abs/2402.11609) - первичный источник про разные роли метрик в decision rule: success, guardrail, deterioration и quality metrics.
- [Statistical Challenges in Online Controlled Experiments](https://arxiv.org/abs/2212.11366) - обзор, который помогает связать guardrails с культурой trustworthy experimentation и множеством метрик.
- [Урок про дерево метрик](../../01-metric-tree/docs/ru.md) - вернитесь к роли `guardrail` и `expected_direction` в metric specs.
- [Урок про монетизацию](../../07-monetization/docs/ru.md) - повторите complete-window policy и денежные failure modes перед интерпретацией refunds.
