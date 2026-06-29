# Regression adjustment и g-formula

> Regression adjustment отвечает на вопрос «как усреднить predicted potential outcomes», но не доказывает, что adjustment set идентифицирует эффект.

**Тип:** Build  
**Треки:** Decision, Product  
**Пререквизиты:** 13/04 — Colliders, mediators и selection bias  
**Время:** ~90 минут  
**Результат:** оценивает standardized potential outcomes и ATE/ATT через outcome
regression, сверяет ручную g-computation со statsmodels и диагностирует misspecification,
extrapolation и неверный adjustment set.

## Цели обучения

- Собрать target-population analysis cohort из target trial spec.
- Отличать naive treated/control difference от standardized g-computation estimate.
- Предсказывать `Y^1` и `Y^0` для одной и той же population.
- Понимать, что ATE и ATT отличаются aggregation population.
- Сверять ручной OLS estimator со `statsmodels.OLS`.
- Выпускать diagnostics по LPM bounds, support/extrapolation, bad controls и claim policy.

## Проблема

После `13/04` у нас есть gate: future estimators могут использовать только
`recommended_pre_treatment_set`. Но это ещё не estimate. Бизнес всё равно спросит:

```text
Окей, а число какое?
```

Самая опасная реакция — открыть regression, добавить все доступные колонки и назвать
коэффициент treatment «эффектом». У нас уже есть запреты:

- нельзя добавлять mediator `onboarding_completed_48h`;
- нельзя фильтровать по `telemetry_complete_30d`;
- нельзя использовать outcome/downstream outcome как feature;
- нельзя забывать, что `latent_motivation` остаётся unmeasured limitation.

В этом уроке мы делаем первый прозрачный estimator:

```text
target population -> outcome model -> predict Y under T=1 and T=0 -> average contrast
```

Это regression adjustment / g-formula. Он полезен, но не магичен: report может быть
валидным как estimate artifact и одновременно запрещать unrestricted causal claim.

## Концепция

### Naive difference сравнивает разные группы

В tiny cohort target population содержит 10 users:

```text
treated = 6
comparator = 4
```

Observed activation:

```text
treated risk = 4 / 6 = 0.6667
comparator risk = 3 / 4 = 0.7500
naive risk difference = -0.0833
```

Но treated users имеют другой baseline risk: помощь чаще доставалась пользователям с
высоким friction. Naive difference остаётся association, а не causal effect.

### G-formula стандартизирует predictions

Outcome model оценивает:

```text
E[Y | T, X]
```

Затем для каждой строки target population строятся две копии:

```text
row with T = 1 -> predicted Y^1
row with T = 0 -> predicted Y^0
```

Для ATE:

```text
mean(predicted Y^1 - predicted Y^0 over all target-population rows)
```

Для ATT:

```text
mean(predicted Y^1 - predicted Y^0 over rows actually treated)
```

В текущей additive LPM-модели ATE и ATT совпадают, потому что treatment effect constant
by model construction. Это не закон природы, а следствие выбранного model basis.

### Adjustment set и model basis — не одно и то же

`13/03` и `13/04` говорят, какие variables разрешены как observed baseline sources.
Но tiny profile содержит всего 10 analysis rows. Если развернуть все 11 covariates в
широкую dummy-модель, мы получим красивую, но бессмысленную rank-deficient regression.

Поэтому artifact использует compact teaching basis:

```text
intercept
treatment
baseline_risk_score
specialist_capacity
```

`baseline_risk_score` — не propensity score и не ML-модель. Это заранее заданный
derived feature, построенный только из allowed observed baseline sources:

```text
platform
device_tier
acquisition_channel
region_id
language
network_quality
app_crashes_before_time_zero
onboarding_steps_before_time_zero
sessions_before_time_zero
friction_score
```

Так урок сохраняет две дисциплины:

- не протаскивать bad controls;
- не притворяться, что маленькая учебная regression покрывает все modeling risks.

### Linear probability model удобен для ручной сверки, но требует warnings

Outcome `activation_14d` бинарный. Урок использует linear probability model:

```text
Y = b0 + b1 * T + b2 * baseline_risk_score + b3 * specialist_capacity + error
```

Почему не сразу logistic regression? Потому что здесь важна прозрачная g-computation:
ручной least squares должен совпасть со `statsmodels.OLS` до численного tolerance.

Цена этой прозрачности:

- LPM может предсказывать probability меньше 0 или больше 1;
- маленький cohort вынуждает extrapolate counterfactuals за observed support;
- robust standard errors не исправляют confounding или misspecification.

Report поэтому содержит warning checks, а не прячет ограничения.

## Соберите это

Артефакты урока:

```text
outputs/g_formula_spec.json
outputs/g_computation_estimator.py
outputs/g_formula_estimate_report.json
```

### Шаг 1: соберите analysis cohort

Estimator читает:

```text
../data/tiny/users.csv
../data/tiny/pre_treatment_behavior.csv
../data/tiny/onboarding_assistance.csv
../data/tiny/outcomes.csv
```

Затем применяет target-population criteria из `target_trial_spec.json`:

```json
[
  {"field": "is_test_user", "operator": "==", "value": false},
  {"field": "eligible_for_program", "operator": "==", "value": true},
  {"field": "friction_score", "operator": ">=", "value": 50}
]
```

Treatment определяется как actual `received_assistance` со стартом после time zero и не
позже 24 часов. Offer alone не считается treatment.

### Шаг 2: постройте model matrix вручную

`g_formula_spec.json` задаёт terms:

```json
["intercept", "treatment", "baseline_risk_score", "specialist_capacity"]
```

Ручной estimator решает least-squares задачу:

```python
beta = np.linalg.lstsq(X, y, rcond=None)[0]
```

Затем библиотечная проверка делает то же через:

```python
statsmodels.api.OLS(y, X).fit(cov_type="HC1")
```

Сверка коэффициентов и standardized effects должна пройти с tolerance `1e-10`.

### Шаг 3: стандартизируйте potential outcomes

Для каждой строки cohort estimator строит два design matrix:

```text
X(T=1)
X(T=0)
```

и считает:

```text
predicted_y_if_treated
predicted_y_if_comparator
individual_contrast
```

На tiny profile report получает:

```json
{
  "naive_risk_difference": -0.08333333333333337,
  "mean_y_if_treated": 0.5400875992335064,
  "mean_y_if_comparator": 0.9398686011497391,
  "manual_ate": -0.39978100191623295,
  "manual_att": -0.39978100191623295
}
```

Не трактуйте знак как продуктовый вывод. Это учебная estimate под очень маленькой,
ограниченной и assumption-sensitive моделью.

### Шаг 4: выпустите diagnostics

Валидный report всё равно содержит warnings:

```text
linear_probability_predictions_within_probability_bounds
counterfactual_predictions_stay_within_observed_support
```

Первый warning говорит: LPM вышла за `[0, 1]` для части predictions. Второй говорит:
counterfactual predictions требуют extrapolation. Например, high-risk treated users
предсказываются под no-assistance strategy, хотя в observed control такой risk почти не
встречается.

## Используйте это

Из корня урока:

```bash
python outputs/g_computation_estimator.py \
  --data-dir ../data/tiny \
  --target-trial ../01-causal-question-and-estimand/outputs/target_trial_spec.json \
  --estimand ../01-causal-question-and-estimand/outputs/estimand.json \
  --adjustment-gate ../04-colliders/outputs/bad_control_selection_audit.json \
  --model-spec outputs/g_formula_spec.json \
  --output outputs/g_formula_estimate_report.json
```

Компактный пример:

```bash
python code/main.py
```

Ожидаемый summary:

```json
{
  "estimate_valid": true,
  "cohort_n": 10,
  "treated_n": 6,
  "comparator_n": 4,
  "naive_risk_difference": -0.083333,
  "standardized_ate": -0.399781,
  "effect_claim_allowed": false
}
```

## Сломайте это

### Ошибка 1: включить mediator в outcome model

Добавьте `onboarding_completed_48h` в `direct_numeric_terms` и `terms`. Estimator должен
провалить:

```text
model_uses_only_allowed_baseline_sources
```

Это regression-версия ошибки из `13/04`.

### Ошибка 2: разрешить causal wording

Поменяйте:

```json
"allowed_effect_claim": true
```

Report должен стать invalid через:

```text
claim_policy_respects_unmeasured_confounding_limitation
```

Число есть, но unmeasured backdoor path ещё не исчез.

### Ошибка 3: забыть часть adjustment sources

Candidate `too_narrow_friction_capacity_model` намеренно использует только:

```text
friction_score
specialist_capacity
```

Он должен получить:

```text
invalid_omits_required_adjustment_sources
```

### Ошибка 4: сломать treatment timing

Если `started_at` выходит за 24-часовой grace period, estimator блокирует cohort до
расчёта. Treatment definition — часть estimand, а не техническая деталь.

## Проверьте это

Behavioral tests проверяют:

- tiny g-formula numbers и cohort counts;
- ручной OLS совпадает со `statsmodels.OLS`;
- standardization строит `Y^1` и `Y^0` для тех же rows;
- LPM bounds и support/extrapolation warnings не теряются;
- model basis использует только allowed baseline sources;
- too-narrow, mediator leakage и complete-case variants отклоняются;
- duplicate source grain и treatment timing violation блокируют estimate;
- CLI пишет report и возвращает non-zero для invalid spec.

Запуск:

```bash
python -m unittest tests/test_main.py
```

## Поставьте результат

Именованный артефакт:

```text
g-computation-estimator
```

Он передаёт дальше:

- target-population cohort audit;
- naive association baseline;
- ручной и statsmodels outcome regression;
- standardized potential outcomes;
- ATE/ATT estimates;
- model diagnostics и claim policy.

Важно: артефакт не завершает причинное исследование. Он готовит оценку для сравнения с
matching, IPW/AIPW и sensitivity checks в следующих уроках.

## Упражнения

1. Добавьте treatment interaction с `baseline_risk_score`. Почему ATE и ATT теперь могут
   различаться?
2. Замените LPM на logistic regression как эксперимент. Какие части manual
   standardization останутся теми же?
3. Уберите `region_id` из source coverage candidate model и объясните, какой backdoor
   риск возвращается.
4. Сравните users, которые требуют extrapolation под `T=0`, с их friction score и
   assignment reason.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Regression adjustment | «Коэффициент treatment и есть causal effect» | Outcome-regression estimator для identified expression при stated assumptions |
| G-formula | «Обычная regression summary» | Standardization predicted potential outcomes over target population |
| ATE | «Среднее среди treated минус среднее среди control» | Средний individual contrast по target population |
| ATT | «То же самое, что ATE» | Средний individual contrast по фактически treated population |
| Extrapolation | «Модель умеет предсказывать везде» | Prediction за observed support treatment-specific covariates |
| LPM | «Плохая модель, значит бесполезна» | Прозрачный linear-probability baseline с обязательными bounds diagnostics |

## Дополнительное чтение

- [Hernán and Robins: Causal Inference: What If](https://miguelhernan.org/whatifbook) — главы про standardization и parametric g-formula как основу regression adjustment.
- [statsmodels OLS documentation](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html) — API, fit results и covariance options, которые используются для library cross-check.
- [statsmodels Treatment Effects](https://www.statsmodels.org/stable/treatment.html) — где regression adjustment находится среди RA/IPW/AIPW estimators и какие assumptions остаются на пользователе.
- [DoWhy: Estimating Causal Effects](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html) — как workflow отделяет identification от estimation и refutation.
