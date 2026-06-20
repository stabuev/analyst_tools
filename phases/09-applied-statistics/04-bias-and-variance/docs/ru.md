# Смещение и дисперсия

> Стабильное число может быть стабильно неверным.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/03-estimators`  
**Время:** ~75 минут  
**Результат:** проводит repeated-sampling simulation для нескольких механизмов отбора,
оценивает bias, variance и MSE estimator'ов и объясняет, почему стабильное число может
быть систематически неверным.

## Цели обучения

- Отличать bias estimator'а от variance estimator'а.
- Считать repeated-sampling mean estimate, bias, variance и MSE.
- Показывать, что неполный sampling frame может дать маленькую variance и большой bias.
- Проверять, что weights не чинят coverage и non-response автоматически.
- Выпускать machine-readable CSV/JSON отчет по нескольким estimator'ам.

## Проблема

В `09/03` появились point estimates:

```text
activation_rate_naive     0.800000
activation_rate_weighted  0.843750
```

Они посчитаны на одном sample. Но руководителю продукта не нужен спор двух чисел. Ему
нужно понять, какое правило расчета ведет себя лучше при повторении процесса сбора данных.

Симуляция отвечает на другой вопрос:

```text
Если бы мы много раз повторили sampling mechanism, вокруг какого parameter центрировался бы estimator?
И насколько сильно он колебался бы?
```

Тут появляется неприятная ловушка. Estimator из неполного frame может колебаться меньше,
чем честный simple random sample, но быть дальше от target population.

## Концепция

### Bias

Bias - это расстояние между средним estimate по повторным выборкам и истинным parameter:

```text
bias = mean(estimate_1, ..., estimate_R) - parameter
```

Если target population activation равен `0.625`, а repeated estimates из frame в среднем
дают около `0.71`, estimator систематически завышает activation.

### Variance

Variance - это разброс estimates вокруг их repeated-sampling mean:

```text
variance = mean((estimate_r - mean_estimate)^2)
```

Она отвечает не на вопрос "правильно ли", а на вопрос "насколько дергается".

### MSE

Mean squared error соединяет обе части:

```text
MSE = bias^2 + variance
```

Эта формула полезна как дисциплина мышления: нельзя смотреть только на standard error или
только на отклонение одного sample estimate.

## Соберите это

Начните с конечной population из `data/tiny/population_users.csv`. В ней восемь eligible
non-test пользователей. Истинный activation parameter:

```python
values = [1, 1, 1, 0, 0, 0, 1, 1]
parameter = sum(values) / len(values)
```

Результат:

```text
0.625
```

Теперь представьте три repeated-sampling mechanism:

1. `srs_population` - simple random sample из полной eligible population.
2. `coverage_biased_frame` - sample из frame, где нет одного low-end Android пользователя.
3. `unequal_frame_with_nonresponse` - sample из frame с unequal probabilities и response
   probabilities.

### Шаг 1: повторите выборку

Для одной итерации:

```python
drawn_users = rng.choice(population, size=5, replace=False)
estimate = sum(user.activated_7d for user in drawn_users) / 5
```

Повторите это несколько тысяч раз и сохраните estimates.

### Шаг 2: сравните с parameter

```python
mean_estimate = mean(estimates)
bias = mean_estimate - true_parameter
variance = variance(estimates)
mse = bias * bias + variance
```

### Шаг 3: не дайте weights спрятать проблему

Weighted estimator:

```text
sum(w_i * x_i) / sum(w_i)
```

Но если user вообще не попал в sampling frame, вес не создаст его обратно. Поэтому
`bias_variance_simulator` сравнивает weighted estimator с полной population, а не только с
frame parameter.

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/04-bias-and-variance/outputs/bias_variance_simulator.py \
  --population phases/09-applied-statistics/data/tiny/population_users.csv \
  --frame phases/09-applied-statistics/data/tiny/sampling_frame.csv \
  --spec phases/09-applied-statistics/04-bias-and-variance/outputs/bias_variance_spec.json \
  --output-csv phases/09-applied-statistics/04-bias-and-variance/outputs/bias_variance.csv \
  --output-report phases/09-applied-statistics/04-bias-and-variance/outputs/bias_variance_report.json
```

Фрагмент вывода в `bias_variance.csv`:

```text
mechanism_id,estimator_id,bias,variance,mse,bias_flag
srs_population,activation_naive,...,...,...,False
coverage_biased_frame,activation_naive,...,...,...,True
unequal_frame_with_nonresponse,activation_weighted,...,...,...,True
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/04-bias-and-variance/code/main.py
```

Он печатает compact JSON: истинные parameters и bias/variance summary по каждой паре
`mechanism::estimator`.

## Сломайте это

Попробуйте три поломки.

1. Укажите estimator в mechanism, но не объявите его в `estimators`.

Ожидаемый check:

```text
srs_population_estimators_resolve
```

2. Замените `metric_column` у `activation_rate` на неизвестное поле.

Ожидаемый check:

```text
activation_rate_metric_column_present
```

3. Сделайте `sample_size` больше числа строк source.

Симуляция должна остановиться с понятной ошибкой до выпуска CSV, а не молча заменить
выборку на sampling with replacement.

## Проверьте это

Запустите tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/04-bias-and-variance/tests -v
```

Tests проверяют:

- true parameters считаются по полной eligible population, а не по frame;
- `coverage_biased_frame` имеет bias flag при меньшей variance;
- weighted estimator не лечит missing frame coverage;
- committed `bias_variance.csv` и `bias_variance_report.json` совпадают с runner output;
- CLI пишет оба файла и возвращает machine-readable summary.

## Поставьте результат

Артефакт урока - `outputs/bias_variance_simulator.py`. Он принимает population, sampling
frame и `bias_variance_spec.json`, затем выпускает:

- `outputs/bias_variance.csv` - таблицу по mechanism, estimator, bias, variance и MSE;
- `outputs/bias_variance_report.json` - полный report с checks и true parameters.

Этот CSV нужен следующим урокам: confidence intervals и bootstrap будут строить interval
claims только после понимания, какой estimator смещен и почему.

## Упражнения

1. Увеличьте `sample_size` для `srs_population` и сравните variance с исходным отчетом.
2. Добавьте estimator для `support_tickets_7d` и проверьте, меняется ли bias direction.
3. Ослабьте `bias_threshold` до `0.10` и объясните, почему threshold - это decision rule, а
   не статистический закон.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Bias | Любая ошибка в данных | Repeated-sampling difference между mean estimate и parameter |
| Variance | Насколько разные пользователи в sample | Разброс estimates при повторении sampling mechanism |
| MSE | Просто средняя ошибка одного sample | `bias^2 + variance` для estimator'а |
| Coverage bias | Проблема маленького sample size | Систематическое несовпадение sampling frame и target population |
| Bias flag | Доказательство плохой аналитики | Machine-readable сигнал, что estimator требует ограничения в отчете |

## Дополнительное чтение

- [NumPy: Random Generator](https://numpy.org/doc/stable/reference/random/generator.html) - разделы про `Generator` и sampling operations; нужны для воспроизводимых repeated-sampling simulations.
- [NumPy: `numpy.random.Generator.choice`](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.choice.html) - параметры `replace` и `p`, которые управляют equal и unequal sampling.
- [NIST/SEMATECH e-Handbook: Bias and Accuracy](https://www.itl.nist.gov/div898/handbook/mpc/section1/mpc113.htm) - аккуратное различение bias, precision и accuracy.
- [NIST/SEMATECH e-Handbook: Variance](https://www.itl.nist.gov/div898/handbook/eda/section3/eda356.htm) - напоминание, что variance описывает spread, а не correctness.
