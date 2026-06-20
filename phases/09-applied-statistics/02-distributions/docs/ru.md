# Распределения как модели

> Распределение - не украшение графика, а явное предположение о support, параметрах и том, где модель перестает быть честной.

**Тип:** Learn  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/01-population-and-sample`  
**Время:** ~75 минут  
**Результат:** сопоставляет activation, revenue, support tickets и onboarding duration с
Bernoulli/binomial, lognormal, count и heavy-tailed моделями, проверяя support,
параметры, empirical summaries и failure modes распределения.

## Цели обучения

- Выбирать модель распределения по типу метрики и support, а не по красивой форме графика.
- Отличать Bernoulli-модель отдельного пользователя от binomial sampling distribution для суммы.
- Не передавать нули revenue в lognormal fit без явного zero-mass договора.
- Проверять count support и mean-variance shape перед Poisson-интерпретацией.
- Выпускать `distribution cards` с assumptions и limitations до estimator'ов и интервалов.

## Проблема

После `09/01` команда знает, кого представляет sample и какие sampling risks уже есть:
undercoverage low-end Android, segment-level non-response и unequal inclusion
probabilities. Теперь нужно подготовить статистические модели для метрик.

Плохой ход:

```text
activation_rate = 80%, revenue mean = 784, support tickets mean = 0.4,
onboarding mean = 588 seconds. Дальше построим интервалы.
```

В этих числах смешаны разные процессы:

- `activated_7d` - бинарный outcome одного пользователя;
- `first_order_amount_rub` - денежная величина с нулями и положительным правым хвостом;
- `support_tickets_7d` - count за фиксированное окно;
- `onboarding_seconds` - положительная duration, где mean может быть хуже median как
  описание "типичного" пользователя.

Если не назвать распределительную модель заранее, следующий урок про оценки получит
неявные assumptions. Например, lognormal-интервал по revenue станет неверным, если нули
были незаметно включены в положительную модель. Poisson-интервал для tickets станет
сомнительным, если variance сильно больше mean. Bernoulli-модель activation сломается,
если в колонке появились строки `"unknown"`.

## Концепция

### Распределение начинается с support

Support отвечает на вопрос: какие значения вообще возможны.

| Метрика | Support | Рабочая модель | Главная проверка |
|---|---|---|---|
| `activated_7d` | `{0, 1}` | Bernoulli для пользователя, binomial для суммы | только boolean-значения |
| `first_order_amount_rub` | `0` плюс `x > 0` | zero mass + lognormal для positive amounts | нули не входят в positive fit |
| `support_tickets_7d` | `0, 1, 2, ...` | Poisson count | non-negative integers и dispersion |
| `onboarding_seconds` | `x > 0` | lognormal/right-tail diagnostic | ноль и отрицательные duration запрещены |

Support важнее формы histogram. Если значение невозможно по смыслу, модель уже сломана.

### Bernoulli и binomial отвечают на разные вопросы

Один пользователь либо активировался, либо нет:

```text
X_i ~ Bernoulli(p)
```

Сумма активированных пользователей в `n` одинаково заданных наблюдениях:

```text
S = X_1 + ... + X_n ~ Binomial(n, p)
```

В tiny sample четыре из пяти observed respondents активировались, поэтому `p_hat = 0.8`.
Это не доказывает, что target population activation равен 80%: sampling risks из `09/01`
никуда не исчезли.

### Lognormal не принимает нули

Lognormal-модель живет на `x > 0`. Поэтому revenue с нулевыми заказами нужно разложить:

```text
P(revenue = 0) + distribution(revenue | revenue > 0)
```

В уроке `first_order_amount_rub_positive` явно фиксирует этот договор. Нули остаются в
карточке как `zero_count`, но fit `scipy.stats.lognorm.fit(..., floc=0)` строится только
по положительным суммам.

Для `onboarding_seconds` такого zero mass договора нет: duration должна быть строго
положительной. Поэтому `0` здесь - blocking error.

### Poisson является проверяемым приближением

Poisson-модель для count-метрик говорит не только "значение целое". Она несет shape
assumption:

```text
E[X] = Var[X] = lambda
```

На маленькой выборке dispersion diagnostic слабый, но его все равно нужно выпускать как
machine-readable check. Если later sample покажет сильную overdispersion, Poisson-based
interval станет плохой идеей.

### Distribution card не является доказательством

Карточка распределения фиксирует:

- `metric_id` и колонку;
- family и SciPy API;
- support;
- observed `n`;
- параметры, оцененные на текущем sample;
- empirical summaries;
- checks, assumptions, failure modes и limitations.

Она не утверждает, что мир "на самом деле" Bernoulli, lognormal или Poisson. Это рабочая
модель, которую можно проверить, сломать и заменить.

## Соберите это

Минимальная ручная проверка начинается без SciPy. Для activation достаточно support и
параметра:

```python
values = [True, True, True, False, True]
successes = sum(1 for value in values if value)
n = len(values)
p_hat = successes / n
variance = p_hat * (1 - p_hat)
```

Для count-метрики сначала проверьте, что все значения - неотрицательные целые:

```python
def parse_count(value):
    number = float(value)
    if number < 0 or not number.is_integer():
        raise ValueError("count metric must be a non-negative integer")
    return int(number)
```

Для lognormal-модели не начинайте с `fit`. Сначала разделите нули и положительные
значения:

```python
amounts = [990.0, 1490.0, 0.0, 450.0, 990.0]
zeros = sum(1 for amount in amounts if amount == 0)
positive = [amount for amount in amounts if amount > 0]
```

Если у метрики support `x > 0`, как у `onboarding_seconds`, нули не откладываются в
отдельную массу. Они ломают вход.

## Используйте это

Артефакт урока использует `scipy.stats` после ручных support checks:

```bash
uv run --locked python phases/09-applied-statistics/02-distributions/outputs/distribution_card_builder.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --spec phases/09-applied-statistics/02-distributions/outputs/distribution_spec.json \
  --output phases/09-applied-statistics/02-distributions/outputs/distribution_cards.json
```

Ключевые SciPy-вызовы:

```python
stats.bernoulli.mean(p_hat)
stats.binom.sf(successes - 1, n, p_hat)
stats.lognorm.fit(positive_values, floc=0)
stats.kstest(positive_values, "lognorm", args=(shape, loc, scale))
stats.poisson.pmf(0, lambda_hat)
```

Запустите короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/02-distributions/code/main.py
```

Он печатает families и warning ids:

```json
{
  "valid": true,
  "metric_families": {
    "activation_7d": "bernoulli",
    "first_order_amount_rub_positive": "lognormal_positive",
    "support_tickets_7d": "poisson",
    "onboarding_seconds": "lognormal_positive"
  },
  "warning_ids": [
    "activation_7d_small_sample_model_check",
    "first_order_amount_rub_positive_small_sample_model_check",
    "first_order_amount_rub_positive_zero_mass_documented",
    "onboarding_seconds_right_tail_diagnostic",
    "onboarding_seconds_small_sample_model_check",
    "support_tickets_7d_small_sample_model_check"
  ]
}
```

Warning-и не делают report invalid. Они говорят, что модель можно использовать только с
ограничениями.

## Сломайте это

Попробуйте четыре мутации.

1. Замените `activated_7d` на `"maybe"`.

Ожидаемый blocking check:

```text
activation_7d_boolean_support
```

2. Поставьте `first_order_amount_rub = -10.00`.

Ожидаемый blocking check:

```text
first_order_amount_rub_positive_nonnegative_support
```

3. Поставьте `support_tickets_7d = 1.5`.

Ожидаемый blocking check:

```text
support_tickets_7d_count_support
```

4. Поставьте `onboarding_seconds = 0`.

Ожидаемый blocking check:

```text
onboarding_seconds_positive_support
```

Все четыре ошибки происходят до интервалов, p-value и regression. Это ошибки модели
измерения и support.

## Проверьте это

Запустите tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/02-distributions/tests -v
```

Tests проверяют:

- четыре карточки покрывают declared metric models;
- Bernoulli activation вручную дает `p_hat = 0.8`, `successes = 4`, `failures = 1`;
- revenue fit строится только по positive amounts и документирует zero mass;
- support tickets имеют Poisson count diagnostic и `lambda_hat = 0.4`;
- onboarding duration сохраняет right-tail warning;
- committed `distribution_cards.json` воспроизводится builder'ом;
- invalid boolean, negative revenue, fractional count и zero duration блокируют report;
- CLI пишет JSON и возвращает `1` при blocking error.

## Поставьте результат

Именованный артефакт:

```text
outputs/distribution_card_builder.py
```

Он работает без чтения текста урока:

```bash
python outputs/distribution_card_builder.py \
  --sample ../data/tiny/sample_observations.csv \
  --spec outputs/distribution_spec.json \
  --output distribution_cards.json
```

Готовый handoff:

```text
Distribution cards built for activation_7d, first_order_amount_rub_positive,
support_tickets_7d and onboarding_seconds. Report is structurally valid.
Warnings: small sample diagnostics, revenue zero mass, onboarding right tail.
Do not use these cards as proof of population representativeness; carry sampling
limitations from 09/01 into estimators and intervals.
```

## Упражнения

1. Добавьте в spec метрику `sessions_7d` как count model и проверьте, какие checks нужны
   до Poisson-интерпретации.
2. Измените threshold `tail_ratio_warning_threshold` для `onboarding_seconds` и объясните,
   почему warning исчез или остался.
3. Добавьте mutation-test для revenue, где все положительные суммы равны нулю, и
   сформулируйте понятное сообщение для analyst handoff.
4. На `sample` profile сравните empirical zero rate support tickets с
   `stats.poisson.pmf(0, lambda_hat)` и решите, достаточно ли Poisson приближения.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Support | "Диапазон на графике" | Множество значений, допустимых по смыслу метрики и модели |
| Bernoulli | "Любая доля" | Распределение одного бинарного наблюдения с вероятностью успеха `p` |
| Binomial | "То же самое, что Bernoulli" | Распределение суммы успехов в `n` Bernoulli-наблюдениях |
| Zero mass | "Пропуск или шум" | Отдельная вероятность значения `0`, которую нельзя спрятать в positive-only модель |
| Poisson dispersion | "Косметическая проверка" | Сравнение variance и mean, от которого зависит пригодность Poisson approximation |
| Distribution card | "Описание графика" | Машинный договор: metric, model family, support, parameters, checks и limitations |

## Дополнительное чтение

- [SciPy `bernoulli`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bernoulli.html) — прочитайте support `{0, 1}`, shape parameter `p`, `pmf`, `mean` и `var`; это базовый API для binary outcome.
- [SciPy `lognorm`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.lognorm.html) — разберите support `x > 0`, параметры `s`, `loc`, `scale` и `fit`; это нужно для revenue positive amounts и durations.
- [SciPy `poisson`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.poisson.html) — посмотрите `pmf`, `mean`, `var` и support count-модели; это основа для ticket-rate diagnostics.
- [SciPy `kstest`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kstest.html) — используйте как diagnostic tool осторожно: после fit на тех же данных p-value не является строгим доказательством good fit.
- [NumPy `Generator`](https://numpy.org/doc/stable/reference/random/generator.html) — повторите воспроизводимые симуляции; в следующих уроках distribution assumptions будут проверяться repeated sampling.
