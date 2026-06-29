# Sensitivity analysis и falsification checks

> Хороший causal analysis не заканчивается estimate. Он спрашивает: что должно быть
> неправдой, чтобы наш вывод изменился?

**Тип:** Case  
**Треки:** Decision, Product  
**Пререквизиты:** 13/09 — RDD и instrumental variables: дизайн до оценки  
**Время:** ~75 минут  
**Результат:** проводит placebo treatment/outcome, negative-control и
omitted-confounding sensitivity checks, сравнивает estimates между designs и
формулирует, какая сила нарушения assumptions изменит вывод.

## Цели обучения

- Отличать диагностику, falsification и sensitivity analysis.
- Запускать placebo treatment и placebo outcome checks.
- Использовать negative-control outcome как сигнал residual confounding.
- Поднимать upstream DiD placebo из предыдущего design report.
- Строить простую omitted-confounding sensitivity grid.
- Сравнивать RA/IPW/AIPW, DiD, RDD и IV estimates без незаконного pooling.
- Блокировать strong causal claim, когда refutation checks не выдержаны.
- Формулировать handoff как design-specific evidence, а не «одно итоговое число».

## Проблема

К этому моменту у нас уже есть несколько оценок assisted onboarding:

| Source | Estimate | Meaning |
|---|---:|---|
| naive risk difference | -0.083 | unadjusted association |
| IPW Hájek ATE | -0.085 | ATE under exchangeability/overlap |
| AIPW ATE | -0.387 | doubly robust ATE under assumptions |
| DiD | +0.080 | regional rollout ATT under parallel trends |
| RDD Wald | -1.000 | local cutoff diagnostic on tiny data |
| IV Wald | +0.500 | LATE for compliers |

Соблазнительный, но плохой handoff:

```text
Методы дают разные числа, возьмем среднее.
```

Это ломает смысл causal inference. Эти estimates отвечают на разные вопросы, для разных
популяций и под разными assumptions. Урок делает refutation suite: он не ищет ещё одно
число, а проверяет, можно ли вообще произносить сильный causal claim.

## Концепция

### Falsification check не доказывает assumptions

Placebo и negative controls работают асимметрично:

```text
failed check  -> design выглядит несовместимым с assumptions
passed check  -> assumptions не доказаны
```

Это как дымовой датчик: если пищит — плохо; если молчит — дом не гарантированно безопасен.

В artifact есть четыре falsification checks:

| Check | Идея | Tiny result |
|---|---|---:|
| placebo treatment `even_user_id` | синтетический treatment не должен давать большой эффект | +0.200, pass |
| placebo outcome `activation_14d_pre` | future treatment не должен менять baseline outcome | -0.583, fail |
| negative-control outcome `app_crashes_before_time_zero` | treatment не может менять baseline crashes | +1.167, fail |
| DiD fake rollout placebo | fake rollout в pre-period должен быть около нуля | 0.000, pass |

Главный сигнал: treated и comparator группы уже различались до treatment. Это не
доказывает, что любой estimator неверен, но блокирует сильную формулировку «мы измерили
эффект assisted onboarding».

### Sensitivity analysis спрашивает «насколько сильным должен быть провал»

Primary observational estimate из `13/07`:

```text
AIPW ATE = -0.386875
```

Простая sensitivity grid в уроке моделирует unobserved activation-prone motivation,
которая чаще встречается у comparators:

```text
adjusted_effect = observed_effect + prevalence_imbalance * outcome_effect
```

Чтобы довести estimate до нуля, нужен bias примерно:

```text
0.386875
```

В заданной grid первый nulling scenario:

```text
control_minus_treated_prevalence = 0.4
outcome_risk_difference = 1.0
bias_toward_zero = 0.4
adjusted_effect = +0.013
```

Это не «настоящий Cinelli-Hazlett robustness value», а прозрачная учебная модель. Она
заставляет назвать силу нарушения assumptions, вместо того чтобы писать «возможны
скрытые факторы» и двигаться дальше.

### Нельзя пулить разные estimands

`13/05`-`13/09` дали разные дизайны:

- RA/IPW/AIPW — user-level ATE under conditional exchangeability;
- DiD — regional rollout ATT under parallel trends;
- RDD — local cutoff evidence;
- IV — LATE for compliers.

Даже если все estimates были бы одного знака, их нельзя просто усреднять. В tiny data
они ещё и разнонаправлены:

```text
min estimate = -1.0
max estimate = +0.5
range = 1.5
signs = [-1, +1]
```

Artifact поэтому выпускает policy:

```text
allowed_effect_claim = false
```

И рекомендует design-specific handoff.

## Соберите это

Файлы урока:

```text
outputs/sensitivity_spec.json
outputs/sensitivity_refutation_suite.py
outputs/sensitivity_report.json
```

### Шаг 1: загрузите upstream reports

Suite читает committed reports:

```text
13/07 ipw_aipw_report.json
13/08 did_report.json
13/09 quasi_experiment_report.json
```

Это важное решение: sensitivity analysis идет после estimates и designs, а не
пересчитывает всё заново в отдельной вселенной.

Structural checks:

```text
upstream_reports_are_available
upstream_reports_are_structurally_valid
source_tables_preserve_declared_grain
target_population_is_non_empty
```

Если upstream report отсутствует, CLI с `--fail-on-invalid` возвращает non-zero exit.

### Шаг 2: соберите target population

Target population совпадает с предыдущими user-level estimators:

```text
exclude test users
eligible_for_program = true
friction_score >= 50
```

В tiny data:

```text
cohort_n = 10
```

### Шаг 3: выполните falsification checks

Placebo treatment:

```text
treatment = even_user_id
outcome = activation_14d
effect = 0.2
threshold = 0.25
passes = true
```

Placebo outcome:

```text
treatment = received_assistance
outcome = activation_14d_pre
effect = -0.583
threshold = 0.15
passes = false
```

Negative-control outcome:

```text
treatment = received_assistance
outcome = app_crashes_before_time_zero
effect = +1.167
threshold = 0.5
passes = false
```

Интерпретация: treatment group имела больше baseline crashes и ниже pre-activation.
Это похоже на residual confounding by indication.

### Шаг 4: посчитайте omitted-confounding grid

Spec задает grid:

```json
{
  "control_minus_treated_prevalence_grid": [0.1, 0.2, 0.4, 0.6],
  "outcome_risk_difference_grid": [0.25, 0.5, 0.75, 1.0]
}
```

Каждая ячейка:

```text
bias = prevalence_imbalance * outcome_effect
adjusted_effect = primary_effect + bias
```

Artifact сохраняет все rows и первый scenario, который пересекает ноль.

### Шаг 5: сравните designs без pooling

Estimate comparison table сохраняет:

```text
estimate_id
source
estimand
estimate
poolable = false
```

Check:

```text
design_estimates_are_not_poolable = true
design_estimates_show_directional_disagreement = warning
```

Да, warning специально failed: он нужен, чтобы handoff не спрятал disagreement.

### Шаг 6: примените claim policy

Candidate claims:

| Claim | Status |
|---|---|
| observational_aipw_strong_claim | blocked_by_falsification |
| did_limited_rollout_claim | limited_design_specific_with_warnings |
| iv_late_claim | limited_late_with_unverifiable_assumptions |
| pooled_average_effect_claim | invalid_mixed_estimands |

Final policy:

```text
allowed_effect_claim = false
```

Причины:

```text
falsification_checks_failed
upstream_primary_claim_disallowed
design_estimates_have_opposite_signs
different_estimands_not_poolable
```

## Используйте это

Запуск artifact из корня репозитория:

```bash
python phases/13-causal-analysis/10-sensitivity/outputs/sensitivity_refutation_suite.py
```

Он обновляет:

```text
phases/13-causal-analysis/10-sensitivity/outputs/sensitivity_report.json
```

Короткий пример:

```bash
python phases/13-causal-analysis/10-sensitivity/code/main.py
```

Ожидаемый summary:

```json
{
  "sensitivity_valid": true,
  "cohort_n": 10,
  "primary_effect": -0.386875,
  "falsification_failures": [
    "placebo_outcome_pre_activation",
    "negative_control_outcome_app_crashes"
  ],
  "first_nulling_bias": 0.4,
  "design_estimate_range": 1.5,
  "allowed_effect_claim": false
}
```

Для CI:

```bash
python phases/13-causal-analysis/10-sensitivity/outputs/sensitivity_refutation_suite.py \
  --fail-on-invalid
```

Важно: failed falsification checks не делают pipeline invalid. Они делают causal claim
invalid. Pipeline invalid — это отсутствующий upstream report, сломанный grain или пустая
target population.

## Сломайте это

### Relaxed placebo threshold

Поставьте для `placebo_outcome_pre_activation`:

```json
"max_abs_effect": 0.7
```

Этот check станет pass, но negative-control outcome всё ещё блокирует strong claim.

### Duplicate outcomes

Продублируйте строку в `outcomes.csv`. Check:

```text
source_tables_preserve_declared_grain
```

станет blocking error.

### Missing upstream report

Подмените путь к DiD report на несуществующий. Suite вернет:

```text
valid = false
blocking_checks = ["upstream_reports_are_available"]
```

### Empty target population

Поставьте:

```json
"minimum_friction_score": 999
```

Suite остановится на:

```text
target_population_is_non_empty = false
```

### Pooled average claim

Поменяйте статус `pooled_average_effect_claim` на `claimable_with_assumptions`. Artifact
отклонит declared status: разные estimands нельзя усреднять.

## Проверьте это

Поведенческие тесты:

```bash
python -m unittest phases/13-causal-analysis/10-sensitivity/tests/test_main.py
```

Покрытие:

- committed summary и blocked claim policy;
- runnable `code/main.py`;
- placebo treatment pass;
- placebo outcome и negative-control outcome failures;
- upstream DiD placebo propagation;
- omitted-confounding nulling scenario;
- cross-design estimate comparison и no pooling;
- candidate claim statuses;
- relaxed threshold scenario;
- duplicate source grain;
- empty target population;
- missing upstream report;
- CLI `--fail-on-invalid`;
- committed report reproducibility.

## Поставьте результат

Именованный artifact:

```text
sensitivity-refutation-suite
```

Файлы:

```text
outputs/sensitivity_refutation_suite.py
outputs/sensitivity_spec.json
outputs/sensitivity_report.json
outputs/artifact.json
```

Handoff-фраза:

```text
Do not ship a single strong causal effect claim. The observational AIPW estimate is
-0.387, but placebo pre-activation and negative-control baseline crashes fail, upstream
primary claim was already disallowed, and DiD/RDD/IV target different estimands with
opposite signs. Report design-specific evidence: DiD is rollout-specific, RDD is
local/diagnostic on tiny data, and IV is LATE for compliers under unverifiable exclusion
and monotonicity assumptions.
```

## Упражнения

1. Ужесточите threshold для placebo treatment до `0.1`. Как изменится список
   `falsification_failures`?
2. Уберите из comparison table RDD diagnostic estimate. Останется ли directional
   disagreement?
3. Добавьте sensitivity grid point `0.3 x 1.0`. Достаточно ли его, чтобы пересечь ноль?
4. Сформулируйте stakeholder handoff без слов «доказали эффект».
5. Объясните, почему failed negative control не говорит, какой именно confounder виноват.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Falsification check | «Доказывает, что assumptions верны» | Может опровергнуть design, но успешный check не доказывает assumptions |
| Placebo treatment | «Любая случайная колонка» | Fake treatment, который не должен иметь causal effect на outcome |
| Placebo outcome | «Outcome, который просто не важен бизнесу» | Outcome, который treatment не мог изменить, часто pre-treatment outcome |
| Negative control outcome | «Дешевый дополнительный KPI» | Переменная, на которую treatment не должен влиять, но общие confounders могут |
| Sensitivity analysis | «Сноска про возможные ограничения» | Количественный вопрос о силе нарушения assumptions, меняющей вывод |
| Nulling scenario | «Доказательство отсутствия эффекта» | Конфигурация bias, при которой adjusted estimate пересекает выбранный порог |
| Pooling | «Усреднить все estimates для стабильности» | Допустимо только для совместимых estimands/designs; здесь запрещено |
| Claim policy | «Юридическая перестраховка» | Машинное правило, переводящее diagnostics в допустимую силу вывода |

## Дополнительное чтение

- [Cinelli and Hazlett, 2020](https://doi.org/10.1111/rssb.12348) — primary source по omitted-variable-bias sensitivity через partial R-squared и robustness values.
- [Rosenbaum, 2002](https://link.springer.com/book/10.1007/978-1-4757-3692-2) — классическая книга про observational studies, sensitivity и design thinking.
- [Hernán and Robins, Causal Inference: What If](https://miguelhernan.org/whatifbook) — главы про exchangeability, positivity и почему diagnostics не доказывают assumptions.
- [DoWhy refutation documentation](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/refuting_causal_estimates/index.html) — официальный workflow refuters; полезно сравнить с прозрачным suite из урока.
- [Lipsitch, Tchetgen Tchetgen and Cohen, 2010](https://doi.org/10.1097/EDE.0b013e3181d61eeb) — negative controls как инструмент обнаружения confounding and bias.
