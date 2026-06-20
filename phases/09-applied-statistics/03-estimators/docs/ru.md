# Оценки и свойства оценок

> Estimate - это число; estimator - правило, по которому это число появилось.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/02-distributions`  
**Время:** ~75 минут  
**Результат:** различает parameter, statistic, estimator и estimate, считает naive и
weighted estimators для mean, proportion, quantile и rate и фиксирует estimator spec с
population, filters, weights и standard error.

## Цели обучения

- Разделять `parameter`, `statistic`, `estimator` и `estimate` в одном расчете.
- Считать naive и inverse-probability weighted estimators на user-level sample.
- Не терять sampling warnings из `09/01` при выпуске point estimates.
- Проверять, что distribution card из `09/02` существует для каждой оцениваемой метрики.
- Понимать, почему standard error - свойство estimator'а, а не просто колонка рядом с числом.

## Проблема

После `09/01` известно, что sample структурно пригоден, но несет риски:

```text
frame_segment_coverage
sample_segment_response
unequal_inclusion_probabilities_declared
```

После `09/02` известно, какие модели распределений допустимы для activation, revenue,
support tickets и onboarding duration. Теперь хочется написать:

```text
activation = 80%
revenue = 784 RUB
support tickets = 0.4 per user
```

Но это все еще не статистический вывод. Это просто числа по observed rows. Для честного
handoff нужно сказать:

```text
parameter: что хотим узнать о target population
statistic: какую функцию считаем на sample
estimator: какое правило используем, включая weights
estimate: какое число получилось на конкретных данных
```

Без этого наивная доля activation `0.8` и weighted доля `0.84375` выглядят как два
конкурирующих ответа. На самом деле это два разных estimator'а с разными assumptions.

## Концепция

### Четыре слова, которые нельзя смешивать

| Слово | Вопрос | Пример |
|---|---|---|
| Parameter | Какое неизвестное свойство target population хотим оценить? | Population share activated within seven days |
| Statistic | Какую функцию можно посчитать на sample? | Unweighted sample proportion |
| Estimator | Какое правило связывает sample с parameter? | Inverse-probability weighted proportion |
| Estimate | Какое число получилось на этих данных? | `0.84375` |

Parameter обычно неизвестен. Statistic и estimate видны в файле. Estimator - выбранная
методология, и именно ее нужно проверять.

### Weighted estimate не является магической правдой

В `09/01` sampling frame объявил unequal inclusion probabilities. Поэтому вес
`sample_weight` нельзя игнорировать в population-oriented estimator spec.

Weighted mean считается так:

```text
sum(w_i * x_i) / sum(w_i)
```

Но это не лечит все. Веса учитывают inclusion mechanism, а non-response и coverage gaps
остаются limitations. Поэтому `estimator_runner` переносит warning ids из sampling audit
в каждый estimate.

### Standard error относится к sampling distribution

Point estimate отвечает "какое число получилось". Standard error отвечает "насколько это
правило менялось бы при повторных выборках". В этом уроке standard error считается только
как легкий plugin diagnostic:

- Bernoulli proportion: `sqrt(p_hat * (1 - p_hat) / n)`;
- weighted mean/proportion/rate: weighted variance через effective sample size;
- quantile: не считаем до bootstrap, потому что для медианы в маленькой выборке лучше
  явно перейти к resampling в `09/06`.

Интервалы еще не строим. Для них нужен следующий договор: confidence level, assumptions и
coverage.

## Соберите это

Начните с ручной версии weighted activation. В observed rows есть пять пользователей:

```text
activated: 1, 1, 1, 0, 1
weights:   2, 2, 2.5, 1.666667, 2.5
```

Naive estimator:

```python
values = [1, 1, 1, 0, 1]
activation_naive = sum(values) / len(values)
```

Результат:

```text
0.8
```

Weighted estimator:

```python
values = [1, 1, 1, 0, 1]
weights = [2, 2, 2.5, 1.666667, 2.5]
activation_weighted = sum(w * x for w, x in zip(weights, values)) / sum(weights)
```

Результат:

```text
0.84375
```

Эта разница не говорит, что weighted estimate "истинный". Она говорит, что estimator
использует declared inclusion probabilities. Non-response warning остается рядом.

### Шаг 1: объявите estimator spec

В `outputs/estimator_spec.json` каждый estimator имеет:

```json
{
  "estimator_id": "activation_rate_weighted",
  "parameter": "Population share of eligible users activated within seven days.",
  "statistic": "Inverse-probability weighted sample proportion of activated_7d among observed respondents.",
  "estimator": "inverse_probability_weighted_proportion",
  "metric_column": "activated_7d",
  "weights": {"column": "sample_weight"},
  "distribution_card_metric_id": "activation_7d"
}
```

Spec пишется до расчета. Это скучная, но очень полезная страховка: если в тексте отчета
появляется число без parameter или estimator, оно не готово к handoff.

### Шаг 2: проверьте upstream artifacts

`estimator_runner` читает:

- `upstream_sampling_audit.json` из механики `09/01`;
- `distribution_cards.json` из `09/02`;
- `sample_observations.csv`;
- `estimator_spec.json`.

Если sampling audit invalid, estimates не выпускаются. Если distribution card не
резолвится, estimator spec считается неполным.

### Шаг 3: посчитайте estimate и diagnostic standard error

Для weighted estimator runner сохраняет:

```text
sum_weights
effective_n
standard_error
```

`effective_n` нужен, чтобы студент увидел цену весов: наблюдений формально пять, но
weighted effective sample size получается `4.887828`.

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/03-estimators/outputs/estimator_runner.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --spec phases/09-applied-statistics/03-estimators/outputs/estimator_spec.json \
  --sampling-audit phases/09-applied-statistics/03-estimators/outputs/upstream_sampling_audit.json \
  --distribution-cards phases/09-applied-statistics/02-distributions/outputs/distribution_cards.json \
  --output-estimates phases/09-applied-statistics/03-estimators/outputs/point_estimates.csv \
  --output-report phases/09-applied-statistics/03-estimators/outputs/estimator_report.json
```

Фрагмент результата:

```text
activation_rate_naive                         0.800000
activation_rate_weighted                      0.843750
first_order_amount_rub_weighted_mean        767.343740
onboarding_seconds_median                   520.000000
support_tickets_per_user_weighted_rate        0.468750
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/03-estimators/code/main.py
```

Он печатает compact JSON с estimates и warning count. Warning count равен `1`, потому что
sampling audit warnings перенесены в limitations, а не скрыты.

## Сломайте это

Попробуйте четыре поломки.

1. Уберите distribution card `support_tickets_7d`.

Ожидаемый check:

```text
support_tickets_per_user_weighted_rate_distribution_card_resolves
```

2. Поставьте `sample_weight = 0`.

Ожидаемый check:

```text
activation_rate_weighted_weights_positive
```

3. Замените estimator на `magic_average`.

Ожидаемый check:

```text
estimators_supported
```

4. Поставьте `sampling_audit.valid = false`.

Ожидаемый check:

```text
sampling_audit_has_no_blocking_errors
```

Во всех случаях лучше остановиться без числа, чем выпустить estimate без методологии.

## Проверьте это

Запустите tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/03-estimators/tests -v
```

Tests проверяют:

- baseline выпускает пять point estimates;
- каждый estimate содержит parameter, statistic, estimator и estimate;
- naive activation равен `0.8`, weighted activation равен `0.84375`;
- revenue weighted mean включает нулевую выручку как бизнес-массу;
- quantile estimator откладывает standard error до bootstrap;
- support tickets считаются как weighted rate per user window;
- committed CSV и JSON воспроизводятся runner'ом;
- missing distribution card, zero weight, unknown estimator, missing column и invalid
  sampling audit блокируют output;
- CLI пишет `point_estimates.csv` и `estimator_report.json`.

## Поставьте результат

Именованный артефакт:

```text
outputs/estimator_runner.py
```

Он поставляет два файла:

```text
outputs/point_estimates.csv
outputs/estimator_report.json
```

Handoff для следующего урока:

```text
Point estimates are built from explicit estimator specs. Naive activation is 0.8;
weighted activation is 0.84375; weighted revenue mean is 767.34374 RUB; onboarding
median is 520 seconds; weighted support ticket rate is 0.46875 per user window.
All estimates inherit sampling warnings: frame coverage, segment response and unequal
inclusion probabilities. Use these warnings when discussing bias/variance and intervals.
```

## Упражнения

1. Добавьте unweighted mean для `first_order_amount_rub` и сравните его с weighted mean.
2. Добавьте estimator для `sessions_7d` как weighted rate и проверьте distribution card.
3. Измените один `sample_weight` и объясните, как меняются `sum_weights` и `effective_n`.
4. Добавьте estimator с пустым `parameter` и убедитесь, что runner блокирует spec.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Parameter | "То, что лежит в sample" | Неизвестное свойство target population |
| Statistic | "Любое число в отчете" | Функция, посчитанная на sample |
| Estimator | "Получившееся число" | Правило, которое превращает sample в оценку parameter |
| Estimate | "Метод расчета" | Конкретное числовое значение estimator'а на данных |
| Standard error | "Половина confidence interval" | Оценка разброса estimator'а по repeated samples |
| Effective sample size | "Количество строк" | Приближенный размер эквивалентной unweighted выборки после весов |

## Дополнительное чтение

- [NumPy `average`](https://numpy.org/doc/stable/reference/generated/numpy.average.html) — разберите формулу weighted average `sum(a * weights) / sum(weights)` и ограничения на веса; это production API, с которым сверяется ручная формула урока.
- [SciPy `stats.sem`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.sem.html) — посмотрите, как SciPy определяет standard error of the mean и почему `ddof` является частью методологического договора.
- [NIST: confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section1/prc14.htm) — прочитайте объяснение repeated-sampling смысла интервала; следующий урок будет строить интервалы поверх point estimates.
- [SciPy `bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) — заранее посмотрите, как arbitrary statistic превращается в bootstrap interval; это особенно важно для quantile estimator.
