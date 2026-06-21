# Множественные проверки

> Чем больше гипотез вы проверяете после эксперимента, тем легче найти случайный
> "сигнал". Multiple-testing policy фиксирует, какие проверки могут влиять на решение,
> а какие остаются диагностикой.

**Тип:** Case  
**Треки:** Product  
**Пререквизиты:** 10/07 - Снижение дисперсии и CUPED  
**Время:** ~75 минут  
**Результат:** объявляет families of hypotheses для primary, guardrail, secondary и
exploratory metrics, применяет gatekeeping, Holm/Bonferroni или FDR policy и блокирует
cherry-picking по сегментам.

## Цели обучения

- Разделить экспериментальные метрики на primary, guardrail, secondary и exploratory
  families.
- Объяснить разницу между family-wise error rate и false discovery rate.
- Применить Bonferroni, Holm и Benjamini-Hochberg/FDR к наборам p-values.
- Использовать gatekeeping: secondary signals не открывают launch decision, если primary
  gate провален.
- Пометить post-hoc сегменты как exploratory-only, даже если adjusted p-value выглядит
  убедительно.

## Проблема

В `10/05` primary metric не поддержала запуск:

```text
activation_rate_7d p_value = 0.931981
practical_status = missed_primary_direction
```

В `10/07` CUPED сделал estimate менее шумным, но не изменил решение:

```text
activation_rate_7d adjusted lift = -0.416667
cuped p_value = 0.804109
```

При этом в secondary metric виден красивый сигнал:

```text
paywall_to_trial_conversion_7d raw p_value = 0.012674
```

И еще можно найти сегмент:

```text
activation_rate_7d_by_country_ru p_value = 0.004
```

Если смотреть только на эти две строки, легко рассказать историю:

```text
Primary не вырос, зато trial conversion значимо выросла, а в RU сегменте activation
сильно лучше. Давайте запускать на часть пользователей.
```

Это cherry-picking. До эксперимента команда обещала принимать решение по primary metric и
guardrails. Secondary metrics помогают понять механизм, а сегменты требуют отдельного
подтверждения или заранее объявленной segment policy.

## Концепция

### Family of hypotheses

Family - это набор проверок, которые отвечают на один тип вопроса и вместе создают риск
ложноположительных выводов.

В этом уроке policy объявляет четыре family:

```text
primary     - activation_rate_7d
guardrail   - support tickets, cancellations, refunds
secondary   - trial conversion, realized revenue per user
exploratory - segment candidates
```

Primary проверяется отдельно, потому что это единственный launch gate. Guardrails идут
одной family, потому что любой вредный guardrail должен остановить rollout. Secondary
metrics рассматриваются вместе как диагностические сигналы. Exploratory candidates
показывают идеи для следующих экспериментов, но не становятся основанием для решения.

### FWER и FDR

Family-wise error rate (FWER) контролирует риск хотя бы одного ложноположительного вывода
внутри family. Это строгий режим, поэтому он хорошо подходит для guardrails:

```text
method = holm
```

False discovery rate (FDR) контролирует ожидаемую долю ложных находок среди найденных
сигналов. Это мягче и полезно для secondary/exploratory анализа:

```text
method = fdr_bh
```

Вручную реализованные поправки в артефакте сверяются с `statsmodels` и `scipy`, чтобы
студент видел и механику, и production API.

### Gatekeeping

Gatekeeping задает порядок интерпретации:

```text
1. Primary должен пройти statistical и practical gate.
2. Guardrails должны быть clear.
3. Secondary metrics могут поддержать решение, но не заменить primary.
4. Exploratory findings не используются как launch gate.
```

Поэтому adjusted secondary signal:

```text
paywall_to_trial_conversion_7d adjusted p_value = 0.025348
```

остается `blocked_by_primary`, потому что `activation_rate_7d` не прошла primary gate.

### Post-hoc сегменты

Сегмент `country = RU` не был predeclared segment dimension в protocol. Его p-value:

```text
0.004 -> adjusted 0.008
```

не делает его decision-ready. Отчет сохраняет предупреждения:

```text
post_hoc_candidate
segment_dimension_not_predeclared
exploratory_only_not_a_launch_gate
```

Сегмент можно вынести в новую гипотезу, но нельзя задним числом превратить в подтверждение
успешного эксперимента.

## Соберите это

Откройте `outputs/multiple_testing_policy_checker.py`. Артефакт делает семь шагов.

### Шаг 1: загрузите результаты предыдущих уроков

Checker не пересчитывает эффект с нуля. Он берет проверенные артефакты:

```text
10/01 experiment_protocol.json
10/05 effect_results.csv
10/05 assumption_checks.json
10/06 bootstrap_intervals.json
10/07 variance_reduction_report.json
10/07 cuped_effects.csv
```

Так multiple-testing layer не меняет denominator, window или estimand после просмотра
результата.

### Шаг 2: объявите policy

`outputs/multiple_testing_policy.json` фиксирует alpha, families и methods:

```json
{
  "alpha": 0.05,
  "families": [
    {"name": "primary", "method": "none"},
    {"name": "guardrail", "method": "holm"},
    {"name": "secondary", "method": "fdr_bh"},
    {"name": "exploratory", "method": "fdr_bh"}
  ]
}
```

Policy должна совпадать с protocol. Если в secondary family добавить primary metric, audit
получит blocking failure:

```text
decision_metric_belongs_to_one_family
```

### Шаг 3: соберите hypotheses

Для decision families p-values берутся из `effect_results.csv`. Если CUPED применим к
metric, estimate показывается как sensitivity:

```text
activation_rate_7d effect_source = cuped_sensitivity
effect_p_value_source = raw_p_value; cuped_effects_p_value=0.804109
```

Raw p-value остается основной колонкой множественных проверок этого урока, а CUPED
показывает, что даже adjusted estimate не спасает primary gate.

### Шаг 4: примените поправки

Для guardrail family используется Holm:

```text
support_ticket_rate_7d adjusted p_value = 1.0
subscription_cancel_rate_14d adjusted p_value = 1.0
refund_rate_7d adjusted p_value = 1.0
```

Для secondary family используется Benjamini-Hochberg:

```text
paywall_to_trial_conversion_7d raw p_value = 0.012674
paywall_to_trial_conversion_7d adjusted p_value = 0.025348

realized_revenue_per_user_7d raw p_value = 0.078355
realized_revenue_per_user_7d adjusted p_value = 0.078355
```

### Шаг 5: сверяйте ручную реализацию с библиотеками

Артефакт вручную реализует:

```text
none
bonferroni
holm
fdr_bh
```

Затем сверяет результаты с:

```python
statsmodels.stats.multitest.multipletests
scipy.stats.false_discovery_control
```

Это защищает от тихой ошибки в ранжировании p-values.

### Шаг 6: примените gates

Отчет получает:

```text
primary_gate_passed = false
guardrail_gate_clear = false
launch_allowed_by_multiple_testing = false
```

Guardrails не дают clear не потому, что adjusted p-value значим, а потому что в `10/05`
они остались в `watch` status. Multiple-testing policy не должна замазывать domain risk.

### Шаг 7: вынесите exploratory findings отдельно

Exploratory candidates тоже получают adjusted p-values:

```text
activation_rate_7d_by_acquisition_channel_paid_search adjusted p_value = 0.021
activation_rate_7d_by_country_ru adjusted p_value = 0.008
```

Но обе строки имеют:

```text
decision_eligible = false
decision_reason = not_pre_registered_launch_gate
```

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/08-multiple-testing/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "ready_for_decision": false,
  "hypotheses_evaluated": 8,
  "primary_gate_passed": false,
  "secondary_adjusted_signals": [
    "paywall_to_trial_conversion_7d"
  ],
  "launch_allowed_by_multiple_testing": false
}
```

CLI артефакта:

```bash
uv run --locked python outputs/multiple_testing_policy_checker.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --policy-spec outputs/multiple_testing_policy.json \
  --effect-results ../05-means-and-proportions/outputs/effect_results.csv \
  --bootstrap-report ../06-bootstrap/outputs/bootstrap_intervals.json \
  --cuped-report ../07-cuped/outputs/variance_reduction_report.json \
  --cuped-effects ../07-cuped/outputs/cuped_effects.csv \
  --assumption-checks ../05-means-and-proportions/outputs/assumption_checks.json \
  --output-report /tmp/phase10-multiple-testing-report.json \
  --output-adjusted-results /tmp/phase10-adjusted-results.csv \
  --output-manifest /tmp/phase10-multiple-testing-manifest.json
```

Команду выше запускайте из `phases/10-experiments/08-multiple-testing`.

## Сломайте это

Проверьте failure modes:

```text
secondary family не совпадает с protocol
metric_id встречается одновременно в primary и secondary
family method не поддерживается
upstream effect analysis invalid
post-hoc segment пытаются пометить как decision_use != exploratory_only
```

Ожидаемое поведение:

```text
report.valid = false
blocking_failures содержит id нарушенного правила
CLI завершается с ненулевым кодом
```

Особенно полезная поломка - добавить `activation_rate_7d` в secondary family. Тогда
красивая история "primary не прошла, но secondary прошла" становится машинно невозможной:
одна и та же decision metric не может жить в двух families.

## Проверьте это

Запустите behavioral tests урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/08-multiple-testing/tests -v
```

Suite проверяет:

```text
committed outputs match recalculation
primary gate fails even with CUPED sensitivity
secondary FDR signal is blocked by primary gate
guardrail family uses Holm
exploratory segments are adjusted but never decision eligible
manual adjustments match statsmodels and SciPy
invalid family declarations block policy validity
```

Полная проверка курса после изменения lesson status:

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
outputs/multiple_testing_policy_checker.py
outputs/multiple_testing_policy.json
outputs/multiple_testing_report.json
outputs/adjusted_results.csv
outputs/multiple_testing_manifest.json
```

Главная строка handoff:

```text
Multiple-testing policy is valid, but experiment is not launch-eligible:
primary gate failed, guardrails are still watch, secondary adjusted signal is diagnostic,
and exploratory segment findings are not pre-registered launch gates.
```

Для следующего урока `10/09` этот artifact важен как boundary: peeking audit должен
проверять schedule и alpha-spending поверх уже объявленной multiple-testing policy, а не
переписывать ее после interim looks.

## Упражнения

1. Добавьте в policy вторую synthetic secondary metric с p-value `0.049` и посчитайте,
   как изменятся FDR-adjusted p-values.
2. Замените method guardrail family с `holm` на `bonferroni`. Объясните, почему для трех
   guardrails результат в tiny остается не decision-ready.
3. Попробуйте пометить `activation_rate_7d_by_country_ru` как decision candidate.
   Добейтесь, чтобы тест падал с понятным blocking failure.
4. Сформулируйте один sentence для stakeholder: почему `paywall_to_trial_conversion_7d`
   не может открыть launch decision при проваленной primary metric.

## Ключевые термины

- **Family of hypotheses** - заранее объявленный набор проверок с общим риском ошибки.
- **Family-wise error rate (FWER)** - вероятность хотя бы одного ложноположительного
  вывода в family.
- **False discovery rate (FDR)** - ожидаемая доля ложных находок среди отклоненных
  гипотез.
- **Holm correction** - step-down FWER-поправка, обычно менее консервативная, чем
  Bonferroni.
- **Benjamini-Hochberg** - процедура контроля FDR по отсортированным p-values.
- **Gatekeeping** - заранее заданный порядок, в котором одни проверки открывают или
  блокируют интерпретацию других.
- **Cherry-picking** - выбор понравившегося результата после просмотра множества
  проверок.
- **Post-hoc segment** - сегмент, найденный после анализа результата и не объявленный
  заранее как decision boundary.

## Дополнительное чтение

- [statsmodels: `statsmodels.stats.multitest.multipletests`](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html) - официальный API для Bonferroni, Holm, FDR/BH и других multiple-testing поправок.
- [SciPy: `scipy.stats.false_discovery_control`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html) - официальный API SciPy для контроля false discovery rate методами BH/BY.
- [Benjamini, Hochberg (1995): Controlling the False Discovery Rate](https://www.jstor.org/stable/2346101) - первичная статья о FDR-процедуре, полезная для понимания отличия FDR от FWER.
