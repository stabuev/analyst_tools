# Снижение дисперсии и CUPED

> CUPED делает эксперимент чувствительнее только тогда, когда ковариата была известна до
> treatment и действительно объясняет outcome.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/06 - Bootstrap в экспериментах  
**Время:** ~90 минут  
**Результат:** применяет CUPED/pre-experiment covariate adjustment, проверяет
pre-treatment статус ковариаты, missingness, correlation with outcome, variance
reduction и отсутствие post-treatment leakage.

## Цели обучения

- Построить CUPED-adjusted outcome по формуле `Y - theta * (X - mean(X))`.
- Проверить, что ковариата объявлена в protocol и измерена до treatment exposure.
- Сравнить raw effect и adjusted effect без смены estimand после просмотра результата.
- Измерить correlation, variance reduction и Welch standard error после adjustment.
- Блокировать missing covariates, post-treatment leakage и неподдержанные ratio metrics.

## Проблема

В `10/05` raw effect для primary metric оказался отрицательным:

```text
activation_rate_7d raw lift = -0.666667
```

В `10/06` bootstrap подтвердил, что tiny profile слишком мал для решения. Но команда
спрашивает естественный вопрос:

```text
У нас же есть поведение пользователя до эксперимента. Можно ли им снизить шум?
```

Можно, если это именно pre-treatment информация. В protocol заранее объявлены:

```json
"cuped_policy": {
  "enabled": true,
  "requires_pre_treatment_covariates": true,
  "covariates": ["sessions_7d_pre", "activation_7d_pre"]
}
```

Опасная версия вопроса звучит иначе:

```text
Давайте возьмем любое поле, которое сильнее коррелирует с outcome.
```

Так делать нельзя. Если ковариата появилась после exposure или была выбрана после
просмотра результата, CUPED превращается в leakage.

## Концепция

### Что корректирует CUPED

Для каждого пользователя есть:

```text
Y = outcome в experiment window
X = pre-experiment covariate
```

CUPED строит adjusted outcome:

```text
theta = cov(Y, X) / var(X)
Y_cuped = Y - theta * (X - mean(X))
```

Если `X` связан с `Y`, часть вариации outcome становится предсказуемой и вычитается.
Treatment effect считается тем же способом, что и раньше:

```text
mean(Y_cuped | treatment) - mean(Y_cuped | control)
```

Мы не меняем primary metric. Мы меняем способ оценки той же разницы средних.

### Почему timing важнее красивой корреляции

Допустимые ковариаты:

```text
sessions_7d_pre     - до старта эксперимента
activation_7d_pre   - до старта эксперимента
```

Недопустимые ковариаты:

```text
trial_started_after_exposure
orders_in_experiment_window
support_tickets_after_treatment
```

Post-treatment поле уже могло быть изменено вариантом. Если использовать его для
adjustment, мы частично вычитаем сам treatment effect.

### Variance reduction не равно launch decision

В tiny profile CUPED снижает pooled variance primary outcome:

```text
raw_variance      = 0.300000
adjusted_variance = 0.275000
variance_reduction = 0.083333
```

Но групп всего `3` и `2` пользователя. Отчет остается warning:

```text
control_sample_below_minimum_units
treatment_sample_below_minimum_units
```

CUPED повышает sensitivity, но не отменяет sample-size plan, guardrails, SRM checks,
multiple-testing policy и заранее объявленное decision rule.

## Соберите это

Откройте `outputs/experiment_cuped_adjuster.py`. Артефакт делает шесть шагов.

### Шаг 1: возьмите user-level observations

CUPED не пересчитывает raw events. Он берет уже проверенную таблицу из `10/05`:

```text
metric_observations.csv
effect_results.csv
assumption_checks.json
```

Это защищает от ситуации, когда CUPED и основной effect calculator используют разные
denominator или разные analysis windows.

### Шаг 2: возьмите только объявленные pre-treatment ковариаты

Спецификация `outputs/cuped_spec.json` перечисляет ковариаты:

```json
{
  "name": "sessions_7d_pre",
  "source_table": "pre_experiment_metrics",
  "timing": "pre_treatment"
}
```

Артефакт сверяет их с protocol:

```text
pre_experiment_covariates
cuped_policy.covariates
```

Если ковариата не объявлена или имеет timing `post_treatment`, report становится
invalid.

### Шаг 3: посчитайте theta

Для primary metric:

```text
Y = activation_rate_7d
X = sessions_7d_pre
theta = -0.1
correlation = -0.288675
```

Знак `theta` может быть отрицательным. Это не ошибка: в tiny больше pre-period sessions
случайно оказалось у treatment users, а observed activation у них ниже.

### Шаг 4: постройте adjusted observations

Фрагмент `adjusted_observations.csv`:

```text
U001 control   raw=1.0  X=3.0  adjusted=1.0
U002 treatment raw=0.0  X=5.0  adjusted=0.2
U003 control   raw=0.0  X=1.0  adjusted=-0.2
```

Для бинарной метрики adjusted value может выйти за диапазон `[0, 1]`. Это нормально:
после CUPED это уже не индивидуальная вероятность, а скорректированный вклад в estimator.

### Шаг 5: сравните raw и adjusted effect

Primary:

```text
raw_absolute_lift      = -0.666667
adjusted_absolute_lift = -0.416667
variance_reduction     = 0.083333
```

Secondary trial conversion:

```text
raw_absolute_lift      = 1.000000
adjusted_absolute_lift = 0.250000
variance_reduction     = 0.750000
```

Это хороший сигнал качества ковариаты, но secondary metric не становится launch gate.

### Шаг 6: пропустите неподдержанные метрики явно

`refund_rate_7d` skipped:

```text
ratio metrics require paired numerator/denominator augmentation
```

Простой CUPED по колонке `value` не должен ломать paired numerator/denominator contract
из `10/06`. Ratio metrics требуют отдельного augmentation подхода, поэтому урок честно
оставляет их будущему decision package как diagnostic limitation.

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/07-cuped/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "ready_for_decision": false,
  "metrics_analyzed": 4,
  "primary_raw_lift": -0.666667,
  "primary_adjusted_lift": -0.416667,
  "primary_variance_reduction": 0.083333
}
```

CLI артефакта:

```bash
uv run --locked python outputs/experiment_cuped_adjuster.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --cuped-spec outputs/cuped_spec.json \
  --observations ../05-means-and-proportions/outputs/metric_observations.csv \
  --pre-experiment-metrics ../data/tiny/pre_experiment_metrics.csv \
  --effect-results ../05-means-and-proportions/outputs/effect_results.csv \
  --assumption-checks ../05-means-and-proportions/outputs/assumption_checks.json \
  --output-effects /tmp/phase10-cuped-effects.csv \
  --output-adjusted-observations /tmp/phase10-adjusted-observations.csv \
  --output-report /tmp/phase10-variance-reduction-report.json \
  --output-manifest /tmp/phase10-cuped-manifest.json
```

## Сломайте это

Проверьте failure modes:

1. Поменяйте timing `sessions_7d_pre` на `post_treatment`: report станет invalid из-за
   `covariate_is_pre_treatment`.
2. Замените ковариату primary metric на `support_tickets_7d_pre`: она есть в таблице, но
   не объявлена в protocol CUPED policy.
3. Удалите строку `U005` из `pre_experiment_metrics.csv`: artifact заблокирует adjustment
   из-за missing covariate для analyzed user.
4. Попробуйте применить простой CUPED к `refund_rate_7d`: artifact не будет делать вид,
   что ratio metric можно корректировать как обычную user-level mean.
5. Интерпретируйте `variance_reduction > 0` как launch decision: это ошибка, потому что
   upstream effect analysis всё ещё `ready_for_decision = false`.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/07-cuped/tests -v
```

Они проверяют:

- committed `cuped_effects.csv`, `adjusted_observations.csv`, report и manifest совпадают
  с пересчетом;
- primary raw effect совпадает с `effect_results.csv`, а adjusted effect считается по
  объявленной ковариате;
- secondary trial и revenue остаются diagnostic-only;
- ratio и sparse guardrails explicitly skipped;
- post-treatment covariate, не объявленная ковариата и missing pre-metrics блокируют
  отчет;
- invalid upstream effect analysis блокирует CUPED.

## Поставьте результат

Именованный артефакт:

```text
outputs/experiment_cuped_adjuster.py
outputs/cuped_spec.json
outputs/cuped_effects.csv
outputs/adjusted_observations.csv
outputs/variance_reduction_report.json
outputs/cuped_manifest.json
```

`cuped_effects.csv` станет частью будущего `experiment-decision-package`: он показывает
raw и adjusted lift, theta, correlation, variance reduction, standard error change,
diagnostics и skipped metrics.

## Упражнения

1. Замените primary covariate с `sessions_7d_pre` на `activation_7d_pre` и сравните
   `theta`, `correlation` и `variance_reduction`.
2. Добавьте в tiny еще одного treatment user с низким `sessions_7d_pre` и проверьте, как
   изменится adjusted lift.
3. Реализуйте отдельный exploratory CUPED для `realized_revenue_7d_pre` и объясните, почему
   его нельзя silently добавить в protocol после просмотра результата.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| CUPED | Способ получить значимость из любого A/B-теста | Variance-reduction estimator с заранее объявленной pre-treatment ковариатой |
| Pre-treatment covariate | Любое поле, которое коррелирует с outcome | Признак, измеренный до exposure и не изменяемый вариантом |
| Theta | Настраиваемый бизнес-вес | Коэффициент `cov(Y, X) / var(X)` для вычитания объясненной вариации |
| Adjusted outcome | Новая продуктовая метрика | Технический вклад в estimator той же разницы средних |
| Variance reduction | Разрешение принять launch decision | Диагностика чувствительности, которая не отменяет protocol decision rule |

## Дополнительное чтение

- [Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data](https://www.exp-platform.com/Documents/2013-02-CUPED-ImprovingSensitivityOfControlledExperiments.pdf) - оригинальный CUPED paper; читайте постановку estimator и мотивацию pre-experiment data.
- [From Augmentation to Decomposition: A New Look at CUPED in 2023](https://arxiv.org/abs/2312.02935) - современный primary source о CUPED как augmentation framework и о том, почему ratio/percentile metrics требуют отдельного мышления.
- [SciPy `ttest_ind`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html) - официальный API для Welch comparison adjusted outcomes; полезно сверить `equal_var=False`, alternative и confidence interval semantics.
