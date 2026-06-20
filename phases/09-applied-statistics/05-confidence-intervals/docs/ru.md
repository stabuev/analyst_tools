# Доверительные интервалы

> Интервал - это свойство процедуры, а не гарантия вокруг одного красивого числа.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/04-bias-and-variance`  
**Время:** ~90 минут  
**Результат:** строит confidence intervals для средних и долей через formula-based
standard errors, проверяет confidence level, coverage simulation, малые выборки,
skew/outliers и явно запрещает интервал при нарушенных assumptions.

## Цели обучения

- Связывать confidence level с repeated-sampling coverage.
- Строить normal approximation interval для доли и Student t interval для среднего.
- Отличать warning assumptions от blocking assumptions.
- Проверять coverage на известной finite population.
- Не выпускать lower/upper, если interval method неприменим.

## Проблема

Point estimate без uncertainty звучит увереннее, чем заслуживает:

```text
activation_rate = 0.8
first_order_amount_mean = 784 RUB
```

После `09/04` мы уже знаем, что estimator может быть biased. Теперь нужно добавить вторую
ось честности: насколько сильно estimate колебался бы при повторении sampling procedure.

Плохой handoff:

```text
Activation is 80%, confidence is high.
```

Хороший handoff:

```text
Normal approximation 95% interval for activation is [0.449, 1.000], but tiny sample has
only one failure, so the interval is warning-level and must be checked by coverage or bootstrap.
```

## Концепция

### Confidence level

95% confidence level не означает, что после получения интервала parameter с вероятностью
95% лежит внутри. Parameter фиксирован. Интерпретация процедурная:

```text
если повторять сбор данных и строить интервал тем же методом, примерно 95% таких интервалов
должны покрывать истинный parameter при выполнении assumptions.
```

### Formula intervals

Для доли:

```text
p_hat +- z_(1 - alpha/2) * sqrt(p_hat * (1 - p_hat) / n)
```

Для среднего с неизвестной дисперсией:

```text
x_bar +- t_(1 - alpha/2, df=n-1) * s / sqrt(n)
```

Обе формулы скрывают assumptions. У доли нужны достаточные success/failure counts. У
среднего нужна вменяемая sampling distribution среднего; skew и outliers делают t interval
диагностическим baseline, а не финальным словом.

## Соберите это

Для activation в observed sample:

```python
values = [1, 1, 1, 0, 1]
p_hat = sum(values) / len(values)
se = sqrt(p_hat * (1 - p_hat) / len(values))
critical = norm.ppf(0.975)
```

Получается:

```text
estimate = 0.8
se = 0.178885
interval = [0.449391, 1.000000]
```

Верхняя граница клипуется к `1.0`, потому что proportion не может быть больше единицы. Но
это не исправляет weak assumption: в sample всего один failure.

### Шаг 1: объявите interval spec

`outputs/confidence_interval_spec.json` фиксирует:

- `sample_metric_column` и `population_metric_column`;
- `method`;
- `confidence_level`;
- минимальные требования к `n`, successes и failures;
- distribution card, на которую опирается assumption check.

### Шаг 2: считайте интервал только после checks

Если `minimum_n` нарушен, артефакт пишет:

```text
status = blocked
lower = null
upper = null
```

Так происходит с `support_tickets_normal_95`: пять observed rows недостаточны для
нормального count-baseline.

### Шаг 3: проверьте coverage

Так как tiny population конечна и известна, можно повторять выборки с фиксированным seed и
считать:

```text
coverage_rate = intervals_covering_true_parameter / simulated_intervals
```

Coverage simulation не делает interval "правильным навсегда"; она показывает, как метод
ведет себя в этой учебной population.

В tiny population normal approximation для activation покрывает true parameter заметно
реже номинальных 95%. Это не повод подкрутить формулу; это повод оставить warning и в
следующем уроке перейти к bootstrap/exact alternatives.

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/05-confidence-intervals/outputs/confidence_interval_calculator.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --population phases/09-applied-statistics/data/tiny/population_users.csv \
  --spec phases/09-applied-statistics/05-confidence-intervals/outputs/confidence_interval_spec.json \
  --distribution-cards phases/09-applied-statistics/02-distributions/outputs/distribution_cards.json \
  --output-intervals phases/09-applied-statistics/05-confidence-intervals/outputs/confidence_intervals.csv \
  --output-report phases/09-applied-statistics/05-confidence-intervals/outputs/confidence_interval_report.json
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/05-confidence-intervals/code/main.py
```

Он печатает status, estimate, lower/upper и coverage rate по каждому interval id.

## Сломайте это

1. Уберите distribution card `activation_7d`.

Ожидаемый check:

```text
activation_rate_normal_95_distribution_card_resolves
```

2. Замените method на `magic_interval`.

Ожидаемый check:

```text
interval_methods_supported
```

3. Поднимите `minimum_n` у revenue interval выше числа observed rows.

Ожидаемый результат:

```text
status = blocked
lower = null
upper = null
```

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/05-confidence-intervals/tests -v
```

Tests проверяют:

- activation normal interval совпадает с ручной формулой;
- revenue t interval использует Student t critical value;
- support ticket interval блокируется по `minimum_n`;
- coverage rate считается как repeated-sampling property;
- committed CSV/JSON совпадают с runner output.

## Поставьте результат

Артефакт урока - `outputs/confidence_interval_calculator.py`. Он выпускает:

- `outputs/confidence_intervals.csv` - интервал, status, warnings и coverage по каждому
  interval id;
- `outputs/confidence_interval_report.json` - полный machine-readable report с checks.

Этот результат нужен для `09/06`: bootstrap будет сравниваться с formula intervals там,
где формулы хрупкие.

## Упражнения

1. Замените confidence level `0.95` на `0.90` и объясните, почему интервал стал уже.
2. Добавьте Wilson или exact binomial interval как отдельный method и сравните с normal
   approximation.
3. Сделайте revenue outlier в sample и проверьте, как меняется t interval.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Confidence interval | 95% вероятность, что parameter внутри уже построенного интервала | Процедура, которая при repeated sampling имеет заданную coverage при assumptions |
| Confidence level | Сила уверенности аналитика | Номинальная доля покрытий при повторении процедуры |
| Standard error | Standard deviation данных | Оценка разброса statistic по repeated samples |
| Coverage | Ширина интервала | Доля simulated intervals, покрывших true parameter |
| Blocked interval | Ошибка кода | Явный отказ выпускать интервал при нарушенных assumptions |

## Дополнительное чтение

- [SciPy: `scipy.stats.norm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.norm.html) - `ppf` и `interval` для нормальной аппроксимации.
- [SciPy: `scipy.stats.t`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html) - Student t distribution и degrees of freedom для интервала среднего.
- [SciPy: `scipy.stats.binomtest`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.binomtest.html) - exact binomial test и `proportion_ci` как следующий шаг после хрупкого Wald interval.
- [NIST/SEMATECH e-Handbook: Confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section1/prc14.htm) - повторить смысл confidence coefficient и интервала для mean.
