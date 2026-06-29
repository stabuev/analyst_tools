# Propensity weighting и doubly robust оценка

> Doubly robust не значит «дважды доказано»: estimator устойчивее к misspecification,
> но causal assumptions и overlap всё равно надо показывать явно.

**Тип:** Build  
**Треки:** Decision, Product  
**Пререквизиты:** 13/06 — Matching и баланс ковариат  
**Время:** ~90 минут  
**Результат:** оценивает propensity scores, строит stabilized IPW и AIPW estimates,
проверяет overlap, extreme weights, effective sample size и trimming sensitivity и
сравнивает методы при misspecified treatment или outcome model.

## Цели обучения

- Объяснять propensity score как модель assignment mechanism, а не как «causal score».
- Строить inverse probability weights для ATE и отличать unstabilized от stabilized
  weights.
- Считать IPW Horvitz-Thompson и normalized/Hájek versions и понимать, почему они могут
  расходиться на tiny data.
- Строить AIPW как outcome-regression estimate плюс inverse-weighted residual correction.
- Проверять overlap, tail propensity scores, extreme weights и effective sample size.
- Делать trimming sensitivity и явно показывать изменение target population.
- Блокировать bad controls, complete-case filters и causal wording при оставшемся
  unmeasured confounding.

## Проблема

В `13/05` мы получили outcome-regression g-computation estimate. В `13/06` посмотрели на
matching и увидели, что часть treated users вообще плохо сравнима с controls.

Теперь бизнес спрашивает:

```text
А если не выбрасывать людей через matching, а взвесить всех по вероятности получить помощь?
```

Это естественный следующий estimator. Но в propensity weighting есть две неприятные
ловушки:

- если propensity score близок к `0` или `1`, веса могут стать огромными;
- если propensity model хорошо предсказывает observed treatment, это может означать не
  хороший estimator, а слабый overlap.

В tiny data обычная логистическая регрессия по compact baseline score почти разделяет
treated и controls. Поэтому artifact использует ridge-stabilized logistic propensity
model и всё равно честно пишет overlap warnings.

## Концепция

### Propensity score — это модель treatment assignment

Для каждого пользователя с pre-treatment covariates `X`:

```text
e(X) = P(A = 1 | X)
```

где `A = 1` означает `assisted_within_24h`.

Важно: propensity score не моделирует outcome. Он моделирует, насколько пользователь был
похож на тех, кто получил treatment, с точки зрения observed baseline information.

В уроке primary propensity model:

```text
logit(e(X)) ~ baseline_risk_score + specialist_capacity
```

`baseline_risk_score` — compact teaching basis из `13/05`, построенный только из
разрешенных pre-treatment covariates. Он не удаляет `latent_motivation`, который был
отмечен как unmeasured confounder в `13/03` и `13/04`.

### IPW строит псевдопопуляцию

Для ATE unstabilized weights:

```text
w_i = A_i / e(X_i) + (1 - A_i) / (1 - e(X_i))
```

Stabilized weights умножают числитель на marginal probability observed arm:

```text
sw_i =
  P(A = 1) / e(X_i),       если A_i = 1
  P(A = 0) / (1 - e(X_i)), если A_i = 0
```

Они не меняют смысл inverse probability weighting, но удобнее для диагностики variance и
effective sample size.

В tiny report:

```text
max stabilized weight = 0.909192
max unstabilized weight = 1.563840
stabilized ESS = 9.555332 из 10 rows
```

Сами weights выглядят спокойными, но overlap warning всё равно есть: `U001` имеет
propensity `0.994474`, то есть почти нет comparable controls для counterfactual
`no_assistance` в этой зоне.

### HT и Hájek versions могут расходиться

Horvitz-Thompson IPW ATE:

```text
mean(A * Y / e(X)) - mean((1 - A) * Y / (1 - e(X)))
```

Normalized/Hájek version:

```text
sum(A * Y / e(X)) / sum(A / e(X))
-
sum((1 - A) * Y / (1 - e(X))) / sum((1 - A) / (1 - e(X)))
```

На больших хорошо поддержанных данных они обычно ближе. На tiny data они могут двигаться
в разные стороны:

```text
IPW HT ATE    =  0.078934
IPW Hájek ATE = -0.085192
```

Artifact выносит обе оценки, но primary summary использует Hájek как более стабильную
normalized diagnostic estimate.

### AIPW добавляет residual correction

Outcome model из `13/05`:

```text
E[Y | A, X] ~ A + baseline_risk_score + specialist_capacity
```

Она дает predictions:

```text
m1(X) = E[Y | A=1, X]
m0(X) = E[Y | A=0, X]
```

AIPW estimate:

```text
mean(
  m1(X_i) - m0(X_i)
  + A_i * (Y_i - m1(X_i)) / e(X_i)
  - (1 - A_i) * (Y_i - m0(X_i)) / (1 - e(X_i))
)
```

Интуиция простая: regression adjustment дает baseline estimate, а propensity weights
добавляют поправку за residuals, которые outcome model не объяснила.

В tiny report:

| Метод | Estimate |
|---|---:|
| Naive risk difference | -0.083333 |
| IPW Hájek ATE | -0.085192 |
| Outcome-regression ATE | -0.399781 |
| AIPW ATE | -0.386875 |

Разброс — не баг. Он показывает, что estimator assumptions и model specification реально
важны.

### Double robust не лечит bad identification

AIPW называют doubly robust, потому что при выполненных causal assumptions estimator может
быть consistent, если корректна хотя бы одна из двух nuisance-моделей: treatment model или
outcome model.

Но это не означает:

- можно conditioning on mediators;
- можно игнорировать positivity;
- можно забыть про unmeasured confounding;
- можно выбрать модель по красивому числу.

Artifact поэтому держит `allowed_effect_claim=false`, даже когда calculation valid.

## Соберите это

Артефакты урока:

```text
outputs/ipw_aipw_spec.json
outputs/ipw_aipw_estimator.py
outputs/ipw_aipw_report.json
```

### Шаг 1: соберите target-population cohort

Pipeline читает общие tiny tables фазы:

```text
../data/tiny/users.csv
../data/tiny/pre_treatment_behavior.csv
../data/tiny/onboarding_assistance.csv
../data/tiny/outcomes.csv
```

Затем применяет target trial criteria:

```text
is_test_user == false
eligible_for_program == true
friction_score >= 50
```

Получается тот же cohort, что в предыдущих estimator lessons:

```text
cohort_n = 10
treated_n = 6
comparator_n = 4
naive_risk_difference = -0.08333333333333337
```

### Шаг 2: оцените propensity score

`ipw_aipw_spec.json` задает ridge logistic propensity model:

```json
{
  "model_type": "l2_logistic_regression",
  "alpha": 0.5,
  "terms": ["intercept", "baseline_risk_score", "specialist_capacity"]
}
```

Ручной solver делает Newton iterations с L2 penalty без penalty на intercept. Это нужно,
потому что tiny data слишком мала и обычный unpenalized logistic MLE легко ловит
near-separation.

Контрольные propensity scores:

| User | Treatment | Propensity |
|---|---:|---:|
| U001 | 1 | 0.994474 |
| U006 | 1 | 0.659926 |
| U011 | 0 | 0.360548 |

### Шаг 3: посчитайте IPW weights и ESS

Report пишет unit-level table:

```json
{
  "user_id": "U011",
  "treatment": 0,
  "outcome": 0,
  "propensity_score": 0.36054832011971855,
  "stabilized_ate_weight": 0.625535928023347,
  "unstabilized_ate_weight": 1.5638398200583674
}
```

Effective sample size:

```text
ESS = (sum(weights)^2) / sum(weights^2)
```

В tiny data ESS остается высоким, но это не отменяет overlap tail. Веса могут быть
умеренными, если observed treatment хорошо совпадает с propensity; counterfactual support
всё равно может быть слабым.

### Шаг 4: добавьте outcome model и AIPW

Outcome model считается вручную через matrix OLS и сверяется со `statsmodels.OLS`.
Контроль:

```text
manual_statsmodels_max_param_diff < 1e-10
manual_statsmodels_max_prediction_diff < 1e-10
```

Затем artifact считает:

```text
outcome_regression_ate
ipw_ht_ate
ipw_hajek_ate
aipw_ate
```

### Шаг 5: сделайте trimming sensitivity

Primary trimming schedule:

```json
[0.02, 0.05, 0.1, 0.2, 0.25]
```

Пример из report:

| Threshold | Retained n | Removed users | IPW Hájek | AIPW |
|---:|---:|---|---:|---:|
| 0.05 | 9 | U001 | -0.143656 | -0.385353 |
| 0.10 | 7 | U001, U002, U010 | -0.358463 | -0.441714 |
| 0.20 | 6 | U001, U002, U005, U010 | -0.278435 | -0.418028 |
| 0.25 | 4 | U001, U002, U004, U005, U007, U010 | 0.024048 | -0.169686 |

Чем выше threshold, тем сильнее меняется population. Это sensitivity result, а не
«чистка выбросов».

## Используйте это

Запуск из корня репозитория:

```bash
python phases/13-causal-analysis/07-weighting-and-doubly-robust/outputs/ipw_aipw_estimator.py
```

Скрипт обновляет:

```text
phases/13-causal-analysis/07-weighting-and-doubly-robust/outputs/ipw_aipw_report.json
```

Сокращенный пример:

```bash
python phases/13-causal-analysis/07-weighting-and-doubly-robust/code/main.py
```

Ожидаемые ключевые поля:

```json
{
  "estimator_valid": true,
  "cohort_n": 10,
  "ipw_hajek_ate": -0.085192,
  "aipw_ate": -0.386875,
  "outcome_regression_ate": -0.399781,
  "effect_claim_allowed": false
}
```

Для CI или локального gate:

```bash
python phases/13-causal-analysis/07-weighting-and-doubly-robust/outputs/ipw_aipw_estimator.py \
  --fail-on-invalid
```

`--fail-on-invalid` возвращает non-zero exit code только при blocking checks. Warnings
остаются warnings: они не ломают artifact, но обязаны попасть в интерпретацию.

## Сломайте это

### Bad controls

Если добавить в outcome model:

```text
onboarding_completed_48h
```

artifact вернет invalid, потому что это mediator для total effect.

Если фильтровать cohort по:

```text
telemetry_complete_30d
```

artifact тоже вернет invalid: это post-treatment selection variable.

### Missing adjustment sources

Stress test `misspecified_treatment_friction_capacity` использует только:

```text
friction_score
specialist_capacity
```

Он полезен для обучения, но как primary estimator rejected: модель omits measured
baseline sources из `13/03`.

### Outcome misspecification

Stress test `misspecified_outcome_friction_capacity` оставляет primary propensity model,
но outcome model строит только по `friction_score` и `specialist_capacity`.

Результат:

```text
outcome_regression_ate = 0.081782
AIPW ATE               = 0.067304
```

Это хороший холодный душ: AIPW не спасает estimator, если выбранная модель outcome
выкинула нужный baseline basis, а positivity тоже не идеальна.

### Overlap tail

Primary overlap warning:

```text
U001 propensity = 0.994474
```

Это значит: для very-high-risk treated user почти нет support для counterfactual
`no_assistance`. Report valid, но causal wording restricted.

## Проверьте это

Поведенческие тесты:

```bash
python -m unittest phases/13-causal-analysis/07-weighting-and-doubly-robust/tests/test_main.py
```

Что проверяется:

- expected tiny estimates для naive, IPW HT, IPW Hájek, outcome regression и AIPW;
- unit-level propensity scores и weights;
- ручная AIPW formula по `unit_scores`;
- ESS и overlap warnings;
- trimming sensitivity и removed users;
- misspecified treatment/outcome stress tests;
- rejection bad controls и omitted source variants;
- invalid claim policy при unmeasured confounding;
- duplicate source grain, broken treatment timing и incomplete follow-up;
- CLI `--fail-on-invalid`.

## Поставьте результат

Именованный artifact:

```text
ipw-aipw-estimator
```

Файлы:

```text
outputs/ipw_aipw_estimator.py
outputs/ipw_aipw_spec.json
outputs/ipw_aipw_report.json
outputs/artifact.json
```

Как переиспользовать:

1. Оставьте target trial, estimand и bad-control gate как upstream inputs.
2. Обновите `ipw_aipw_spec.json`: propensity model, outcome model, diagnostics и claim
   policy.
3. Запустите CLI с `--fail-on-invalid`.
4. Передайте downstream не только estimate, но и warnings: overlap tail, ESS, trimming
   sensitivity, model stress tests и `allowed_effect_claim`.

Минимальная фраза для handoff:

```text
Мы получили model-based AIPW estimate -0.3869 under observed-baseline models.
Но primary report содержит overlap warning по high-propensity treated users,
LPM bounds warning и upstream unmeasured confounding; causal claim запрещен.
```

## Упражнения

1. Поменяйте `alpha` ridge propensity model с `0.5` на `1.0`. Как изменились
   propensity tail, IPW Hájek и AIPW?
2. Добавьте trimming threshold `0.15`. Каких users он удаляет и ближе ли estimate к
   primary AIPW или к matched ATT из `13/06`?
3. Создайте candidate estimator с `opened_support_chat_after_offer` в propensity model.
   Какой check должен заблокировать spec?
4. Сравните `misspecified_treatment_friction_capacity` с primary estimator. Почему IPW
   меняет знак, а AIPW остается между misspecified IPW и outcome-regression estimate?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Propensity score | «Оценка склонности к outcome» | Вероятность получить treatment при observed pre-treatment covariates |
| Positivity / overlap | «Достаточно, чтобы были treated и controls вообще» | В каждой релевантной зоне covariate space должны быть обе treatment strategies |
| Stabilized weights | «Исправленные causal weights» | Inverse probability weights с marginal treatment probability в числителе |
| Effective sample size | «Обычный row count» | Размер равновесной выборки с похожей weight concentration |
| Trimming | «Удаление выбросов без последствий» | Ограничение analysis population по propensity support |
| AIPW | «Estimator, которому не нужны assumptions» | Outcome model плюс inverse-weighted residual correction; требует корректного design и хотя бы одной корректной nuisance-модели для double robustness |

## Дополнительное чтение

- [Hernán and Robins, Causal Inference: What If](https://www.hsph.harvard.edu/miguel-hernan/causal-inference-book/) — главы про inverse probability weighting и positivity; лучший источник для связи target trial, weights и интерпретации causal assumptions.
- [Robins, Rotnitzky and Zhao, 1994](https://doi.org/10.1080/01621459.1994.10476818) — первичный источник для semiparametric regression и inverse-probability weighted ideas, которые лежат под doubly robust estimators.
- [Austin and Stuart, 2015](https://doi.org/10.1002/sim.6607) — практический обзор propensity score methods, balance diagnostics и weighting в medical observational studies; полезен для failure modes.
- [statsmodels OLS documentation](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html) — API, с которым artifact сверяет ручную matrix OLS часть outcome model.
- [DoWhy User Guide](https://www.pywhy.org/dowhy/main/user_guide/index.html) — как современные causal libraries разделяют model, identify, estimate и refute; пригодится в финальном `13/11`.
