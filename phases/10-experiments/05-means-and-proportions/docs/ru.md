# Сравнение средних и долей

> `p-value` без denominator, interval и заранее объявленного правила решения не является
> результатом эксперимента.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/04 - MDE, мощность и размер выборки  
**Время:** ~90 минут  
**Результат:** оценивает treatment effect для user-level means, proportions и простых
ratio metrics: absolute/relative lift, confidence interval, p-value, assumption checks и
guardrail status без significance-only решения.

## Цели обучения

- Строить user-level metric observations от exposure window, а не от регистрации или
  календарной даты.
- Считать absolute и relative lift для долей, средних и ratio-of-sums.
- Выбирать Welch t-test для mean metric и two-proportion z-test для proportion/ratio
  metrics.
- Отделять primary launch gate, guardrail gate и secondary diagnostic signal.
- Блокировать продуктовый вывод, если observed sample не соответствует power plan или
  assumptions дают warning.

## Проблема

После `10/01`-`10/04` у команды есть protocol, stable assignment, health gate и power
plan. Теперь появляется соблазн открыть таблицу результатов и сказать:

```text
trial conversion вырос и p-value < 0.05, запускаем treatment.
```

Это неправильный вывод. Trial conversion - secondary metric. Primary metric -
`activation_rate_7d`. Guardrails должны быть не просто "выглядят лучше", а не иметь
практически опасного ухудшения в пределах interval. Кроме того, tiny extract в уроке
содержит пять exposed users, а power plan требовал тысячи пользователей на вариант.

Задача урока - собрать первый честный effect report:

```text
metric observations -> effect table -> assumption checks -> decision status
```

## Концепция

### Analysis unit сначала, тест потом

Protocol объявляет:

```text
randomization_unit = user_id
analysis_unit = user_id
exposure_event = paywall_viewed
```

Поэтому первая таблица анализа - не события и не заказы, а user-level observations:

| user_id | variant_id | metric_id | numerator | denominator | value |
|---|---|---|---:|---:|---:|
| U001 | control | activation_rate_7d | 1 | 1 | 1 |
| U002 | treatment | realized_revenue_per_user_7d | 249 | 1 | 249 |
| U003 | control | refund_rate_7d | 1 | 1 | 1 |

Даже для `refund_rate_7d`, где исходный grain - заказ, артефакт хранит user-level
`numerator/denominator`, а итоговый rate считает как ratio-of-sums. Это защищает от
случайного many-to-many join и от подмены смысла ratio metric средним бинарного флага.

### Lift бывает абсолютным и относительным

Для доли:

```text
control = 2 / 3 = 0.666667
treatment = 0 / 2 = 0.0
absolute_lift = treatment - control = -0.666667
relative_lift = absolute_lift / control = -1.0
```

Абсолютный lift нужен для decision rule и MDE. Relative lift полезен для коммуникации, но
он ломается при control baseline `0`: тогда артефакт явно пишет `inf`, а не прячет деление
на ноль.

### Метод зависит от типа метрики

В уроке используются три типа:

| Тип | Пример | Метод |
|---|---|---|
| Proportion | `activation_rate_7d`, `support_ticket_rate_7d` | two-sample proportions z-test + Newcombe CI |
| Mean | `realized_revenue_per_user_7d` | Welch t-test + Welch confidence interval |
| Ratio | `refund_rate_7d` | z-test на суммарном numerator/denominator |

Это не финальный toolbox для всех экспериментов. Bootstrap для skewed и zero-inflated
metrics будет в `10/06`. Здесь цель - сделать базовый fixed-horizon effect report и
показать, где его assumptions уже требуют осторожности.

### Значимость не равна решению

Tiny extract дает учебный контраст:

| Metric | Role | Absolute lift | p-value | Decision status |
|---|---|---:|---:|---|
| `activation_rate_7d` | primary | -0.666667 | 0.931981 | not launch-ready |
| `paywall_to_trial_conversion_7d` | secondary | 1.0 | 0.012674 | diagnostic only |
| `realized_revenue_per_user_7d` | secondary | 199.0 | 0.078355 | diagnostic only |

Secondary signal не может заменить primary gate. Даже если secondary p-value маленький,
запуск не разрешается без pre-registered primary success и guardrail clearance.

## Соберите это

Откройте `outputs/experiment_effect_calculator.py`. Артефакт делает четыре шага.

### Шаг 1: проверьте upstream gates

Effect calculation начинается не с теста:

```python
if health_report["ready_for_ab_analysis"] is not True:
    block_analysis()

if power_plan["ready_for_sizing"] is not True:
    block_analysis()
```

Если SRM, telemetry loss или power plan сломаны, p-value только маскирует проблему.

### Шаг 2: соберите observations от exposure

Для каждого exposed eligible user артефакт строит шесть metrics из protocol:

```text
activation_rate_7d
support_ticket_rate_7d
subscription_cancel_rate_14d
refund_rate_7d
paywall_to_trial_conversion_7d
realized_revenue_per_user_7d
```

Окно всегда начинается в `exposed_at`, а не в `assigned_at` и не в `registered_at`.

### Шаг 3: рассчитайте effect table

Для каждой metric:

```text
control_value
treatment_value
absolute_lift
relative_lift
confidence interval
p-value
practical_status
decision_status
```

Primary metric получает `launch_gate`, guardrails - `guardrail_gate`, secondary metrics -
`diagnostic_only`.

### Шаг 4: проверьте assumptions

Tiny profile намеренно не проходит часть warning-level checks:

```text
activation_rate_7d:observed_sample_meets_power_plan = false
activation_rate_7d:normal_approximation_cell_counts = false
realized_revenue_per_user_7d:mean_variance_positive = false
```

Это не structural failure, поэтому artifact valid. Но `ready_for_decision = false`.

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/05-means-and-proportions/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "ready_for_decision": false,
  "observation_rows": 30,
  "primary_absolute_lift": -0.666667,
  "primary_p_value": 0.931981,
  "primary_status": "missed_primary_direction",
  "trial_absolute_lift": 1.0,
  "trial_decision_status": "diagnostic_only"
}
```

CLI артефакта:

```bash
uv run --locked python outputs/experiment_effect_calculator.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --metric-specs ../01-hypothesis-and-metric/outputs/metric_specs.json \
  --effect-spec outputs/effect_spec.json \
  --health-report ../03-aa-and-srm/outputs/randomization_health_report.json \
  --power-plan ../04-mde-and-power/outputs/power_plan.json \
  --users ../data/tiny/users.csv \
  --assignments ../data/tiny/assignments.csv \
  --exposures ../data/tiny/exposures.csv \
  --events ../data/tiny/events.csv \
  --orders ../data/tiny/orders.csv \
  --subscriptions ../data/tiny/subscriptions.csv \
  --support-tickets ../data/tiny/support_tickets.csv \
  --output-observations /tmp/phase10-metric-observations.csv \
  --output-effects /tmp/phase10-effect-results.csv \
  --output-assumptions /tmp/phase10-assumption-checks.json
```

## Сломайте это

Проверьте failure modes:

1. Поставьте `ready_for_ab_analysis = false` в health report: calculator не выпустит
   effects.
2. Начните metric window от `assigned_at`: activation counts изменятся и нарушат смысл
   protocol.
3. Посчитайте `refund_rate_7d` как среднее user flag вместо ratio-of-sums: denominator
   станет другим.
4. Разрешите launch по `paywall_to_trial_conversion_7d`: secondary metric подменит
   primary decision rule.
5. Уберите power plan check: tiny sample начнет выглядеть как полноценный результат.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/05-means-and-proportions/tests -v
```

Они проверяют:

- committed observations/effects/assumptions совпадают с расчетом;
- observation table содержит 30 rows: 5 users x 6 metrics;
- primary metric не проходит launch gate;
- secondary trial signal остается `diagnostic_only`;
- guardrails получают `watch`, если harmful delta не исключен interval-ом;
- observed sample сравнивается с power plan из `10/04`;
- upstream health gate блокирует расчет effects.

## Поставьте результат

Именованный артефакт:

```text
outputs/experiment_effect_calculator.py
outputs/effect_spec.json
outputs/metric_observations.csv
outputs/effect_results.csv
outputs/assumption_checks.json
```

`effect_results.csv` и `assumption_checks.json` станут частью будущего
`experiment-decision-package`: они показывают не только численный lift, но и почему
current extract не готов к продуктовой рекомендации.

## Упражнения

1. Измените `feature_value_seen` для `U002` так, чтобы primary treatment value стал `0.5`.
   Объясните, почему это все еще не launch decision.
2. Добавьте refund order для treatment и проверьте, когда `refund_rate_7d` перейдет из
   `watch` в `breached`.
3. Увеличьте tiny extract вручную повторением пользователей нельзя. Объясните, почему
   дубликаты не заменяют настоящий independent sample.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Analysis unit | "Строка исходной таблицы" | Единица, на которой сравниваются варианты; здесь `user_id` |
| Absolute lift | "То же, что относительный рост" | Разность `treatment - control` в исходной шкале метрики |
| Relative lift | "Главное число для решения" | Относительное изменение к control baseline; полезно для коммуникации, но не заменяет MDE |
| Guardrail status | "Если point estimate лучше, все хорошо" | Статус риска с учетом maximum allowed delta и uncertainty |
| Secondary metric | "Запасной primary" | Диагностический сигнал, который не заменяет pre-registered launch gate |
| Ratio metric | "Обычная средняя доля пользователей" | Отношение суммарного numerator к суммарному denominator |

## Дополнительное чтение

- [SciPy `ttest_ind`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html) — официальный API для Welch t-test через `equal_var=False` и направленных альтернатив.
- [statsmodels `proportions_ztest`](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportions_ztest.html) — официальный API для z-test двух долей; обратите внимание на порядок `count`, `nobs` и параметр `alternative`.
- [statsmodels `confint_proportions_2indep`](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.confint_proportions_2indep.html) — официальный API для confidence interval разности долей, включая Newcombe interval.
- [Trustworthy Online Controlled Experiments](https://www.cambridge.org/core/books/trustworthy-online-controlled-experiments/12C54F5F5670A286D3F5A9A7B5BE6DEC) — книга Kohavi, Tang и Xu о том, почему результат эксперимента должен включать метрики, guardrails, качество данных и решение, а не только p-value.
