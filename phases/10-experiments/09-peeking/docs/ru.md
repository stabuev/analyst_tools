# Подглядывание и последовательный анализ

> Если смотреть на p-value каждый день и остановиться при первом удачном числе, alpha
> перестает быть alpha. Interim looks нужно планировать заранее.

**Тип:** Case  
**Треки:** Product  
**Пререквизиты:** 10/08 - Множественные проверки  
**Время:** ~75 минут  
**Результат:** показывает рост false positive rate от незапланированных interim looks,
задает monitoring schedule, alpha-spending или stop/go правила и отличает quality
monitoring от decision peeking.

## Цели обучения

- Объяснить, почему repeated looks по decision metric увеличивают false positive rate.
- Разделить quality monitoring и decision peeking.
- Построить planned decision looks с O'Brien-Fleming/Lan-DeMets alpha spending.
- Проверить, что observed looks не нарушают protocol peeking policy.
- Выпустить sequential monitoring report, который блокирует решение при unplanned peeking.

## Проблема

В `10/08` multiple-testing policy уже сказала: эксперимент не готов к запуску. Primary
gate не прошел, guardrails остались `watch`, secondary signal заблокирован primary gate.

Но в реальной команде до финального freeze почти всегда появляется соблазн:

```text
Давайте просто посмотрим, как идет эксперимент.
```

Смотреть на качество данных можно и нужно:

```text
daily_sample_size
daily_srm
telemetry_loss
```

А смотреть на primary p-value и принимать решение при первом `p < 0.05` нельзя, если это
не было заранее спланировано. В этом уроке observed timeline содержит две опасные строки:

```text
day_05_slack_peek          p = 0.041
day_10_dashboard_refresh   p = 0.018
```

Обе выглядят соблазнительно. Обе не должны открывать launch decision.

## Концепция

### Почему peeking ломает alpha

Fixed-horizon p-value отвечает на вопрос:

```text
Что было бы, если бы мы один раз посмотрели на заранее заданном финальном sample size?
```

Если вместо этого смотреть пять раз и остановиться при первом `p <= 0.05`, вопрос
меняется:

```text
Какова вероятность, что хотя бы один из пяти correlated looks даст p <= 0.05?
```

В симуляции этого урока under null:

```text
1 look  -> false positive rate = 0.0489
5 looks -> false positive rate = 0.14155
```

То есть обычное правило `p <= 0.05` при пяти looks превращается примерно в 14% шанс
ложного открытия.

### Quality monitoring не тратит alpha

Quality monitoring отвечает на вопрос:

```text
Эксперимент технически жив?
```

Допустимые проверки:

```text
sample size набирается
allocation не сломан
telemetry loss не вырос
нет критического SRM
```

Они не смотрят на treatment effect и не используют primary p-value. Если quality dashboard
показывает `activation_rate_7d` по вариантам, это уже не quality-only мониторинг.

### Sequential decision looks тратят alpha

Если команда хочет иметь interim decision, он должен быть объявлен заранее:

```text
interim_50: information_fraction = 0.5
final:      information_fraction = 1.0
```

Для planned interim look артефакт использует O'Brien-Fleming-style Lan-DeMets spending:

```text
alpha = 0.05
interim_50 nominal p boundary = 0.005575
final nominal p boundary      = 0.05
```

Поэтому observed p-value на `interim_50`:

```text
p = 0.031
```

пересекает обычный `0.05`, но не пересекает sequential boundary. Правильное действие:

```text
continue_collecting
```

### Unplanned decision look нельзя легализовать задним числом

`day_10_dashboard_refresh` имеет:

```text
information_fraction = 0.72
p = 0.018
nominal p boundary at 0.72 = 0.020897
```

Даже если бы это был planned look, он выглядел бы сильным. Но он не был planned decision
look в protocol. Поэтому статус остается:

```text
unplanned_decision_peek
```

Нельзя сначала посмотреть результат, а потом объявить, что это был interim analysis.

## Соберите это

Откройте `outputs/peeking_audit.py`. Артефакт делает шесть шагов.

### Шаг 1: загрузите upstream decision context

Peeking audit читает:

```text
10/01 experiment_protocol.json
10/04 power_plan.json
10/08 multiple_testing_report.json
09-peeking/outputs/peeking_policy.json
```

Он не пересчитывает primary effect и не меняет multiple-testing policy. Его задача -
проверить, можно ли было вообще смотреть на decision metrics в те моменты, когда команда
на них смотрела.

### Шаг 2: задайте planned decision looks

Policy содержит:

```json
{
  "planned_decision_looks": [
    {"look_id": "interim_50", "information_fraction": 0.5},
    {"look_id": "final", "information_fraction": 1.0}
  ]
}
```

Финальный look обязателен. Information fractions должны идти строго по возрастанию и
лежать в `(0, 1]`.

### Шаг 3: отделите quality monitoring

Quality-only look:

```json
{
  "look_id": "day_03_quality",
  "metrics_seen": ["daily_sample_size", "daily_srm", "telemetry_loss"],
  "decision_metric_p_value": null
}
```

Такой look получает:

```text
status = quality_only
alpha_spent_cumulative = 0.0
```

Если добавить туда `activation_rate_7d` или `decision_metric_p_value`, audit станет
invalid.

### Шаг 4: посчитайте alpha spending boundaries

Для O'Brien-Fleming-style Lan-DeMets spending:

```text
f(t; alpha) = 2 - 2 * Phi(Phi^-1(1 - alpha / 2) / sqrt(t))
```

Для `alpha = 0.05`:

```text
t = 0.50 -> 0.005575
t = 1.00 -> 0.050000
```

Артефакт считает boundary через `scipy.stats.norm.ppf` и `scipy.stats.norm.cdf`.

### Шаг 5: найдите unplanned decision peeks

Observed looks:

```text
day_05_slack_peek          unplanned_decision_peek
interim_50                 continue_collecting
day_10_dashboard_refresh   unplanned_decision_peek
final                      final_no_launch
```

Decision blockers:

```text
unplanned_decision_look:day_05_slack_peek
unplanned_decision_look:day_10_dashboard_refresh
multiple_testing_does_not_allow_launch
```

### Шаг 6: покажите false positive inflation

Симуляция under null строит Brownian information path для `1`-`5` equally spaced looks.
Для каждого look count сравниваются:

```text
naive rule: p <= 0.05 at any look
O'Brien-Fleming spending boundary
```

Фрагмент `peeking_simulation.csv`:

```text
look_count,naive_false_positive_rate,obrien_fleming_false_positive_rate
1,0.0489,0.0489
5,0.14155,0.05955
```

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/09-peeking/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "ready_for_decision": false,
  "planned_decision_looks": ["interim_50", "final"],
  "unplanned_decision_looks": [
    "day_05_slack_peek",
    "day_10_dashboard_refresh"
  ],
  "interim_50_nominal_p_boundary": 0.005575,
  "interim_50_observed_p_value": 0.031,
  "interim_50_crosses_spending_boundary": false,
  "naive_fpr_at_five_looks": 0.14155
}
```

CLI артефакта:

```bash
uv run --locked python outputs/peeking_audit.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --peeking-policy outputs/peeking_policy.json \
  --power-plan ../04-mde-and-power/outputs/power_plan.json \
  --multiple-testing-report ../08-multiple-testing/outputs/multiple_testing_report.json \
  --output-report /tmp/phase10-sequential-monitoring-report.json \
  --output-schedule /tmp/phase10-monitoring-schedule.csv \
  --output-simulation /tmp/phase10-peeking-simulation.csv \
  --output-manifest /tmp/phase10-peeking-manifest.json
```

Команду выше запускайте из `phases/10-experiments/09-peeking`.

## Сломайте это

Проверьте failure modes:

```text
quality monitoring содержит activation_rate_7d
quality monitoring содержит decision_metric_p_value
policy alpha не совпадает с protocol alpha
нет final decision look
information fractions повторяются или идут не по порядку
upstream multiple-testing report invalid
protocol разрешает unplanned decision looks
```

Ожидаемое поведение:

```text
report.valid = false для policy/protocol contamination
report.ready_for_decision = false при unplanned decision peeks
blocking_failures или decision_blockers объясняют причину
```

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/09-peeking/tests -v
```

Suite проверяет:

```text
committed outputs match recalculation
naive peeking inflates false positive rate
planned interim uses O'Brien-Fleming boundary
unplanned decision looks block decision
quality monitoring does not spend alpha
contaminated quality monitoring invalidates audit
invalid upstream multiple-testing blocks validity
CLI writes report, schedule, simulation and manifest
```

Полная проверка курса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Завершенный урок поставляет:

```text
outputs/peeking_audit.py
outputs/peeking_policy.json
outputs/sequential_monitoring_report.json
outputs/monitoring_schedule.csv
outputs/peeking_simulation.csv
outputs/peeking_manifest.json
```

Главная строка handoff:

```text
Sequential monitoring audit is valid, but decision is blocked:
two unplanned decision looks occurred, interim_50 did not cross the O'Brien-Fleming
boundary, and multiple-testing policy still does not allow launch.
```

Для `10/10` это важно: segment analysis должен использовать только predeclared segment
policy и не превращать dashboard peeks в подтвержденные heterogeneous effects.

## Упражнения

1. Уберите `day_05_slack_peek` и `day_10_dashboard_refresh` из observed looks. Что
   останется блокером решения?
2. Замените `interim_50` p-value на `0.004`. Как изменится status и почему это все еще не
   отменяет guardrails/multiple-testing layer?
3. Добавьте quality-only look, который случайно содержит `activation_rate_7d`. Убедитесь,
   что audit становится invalid.
4. Измените simulation look counts на `[1, 3, 7]` и объясните, почему naive false positive
   rate растет с числом looks.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Peeking | Просто посмотреть dashboard | Просмотр decision metric до planned decision look |
| Interim look | Любой промежуточный dashboard | Заранее объявленная decision-проверка с information fraction и boundary |
| Quality monitoring | Ранний анализ эффекта | Технический мониторинг SRM, объема и telemetry без treatment effect |
| Alpha spending | Способ сделать p-value меньше | Заранее заданное распределение Type I error по planned looks |
| O'Brien-Fleming boundary | Обычный `p <= 0.05` на каждом look | Строгий ранний boundary и более мягкий финальный boundary |
| Information fraction | Доля календарного времени | Доля информации или planned sample, использованная в look |

## Дополнительное чтение

- [gsDesign: Lan-DeMets Spending function overview](https://keaven.github.io/gsDesign/reference/sfLDOF.html) - формула O'Brien-Fleming-style spending function и связь с Lan-DeMets boundaries.
- [SciPy: `scipy.stats.norm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.norm.html) - официальный API для `cdf` и `ppf`, на которых строятся normal z-boundaries в артефакте.
- [Lan and DeMets (1983): Discrete sequential boundaries for clinical trials](https://doi.org/10.1093/biomet/70.3.659) - первичный источник идеи spending functions для group sequential designs.
