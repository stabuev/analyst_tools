# Bootstrap в экспериментах

> Bootstrap не чинит плохой эксперимент, но честно показывает, насколько хрупок
> увиденный effect.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/05 - Сравнение средних и долей  
**Время:** ~90 минут  
**Результат:** строит bootstrap и permutation-based uncertainty для skewed,
zero-inflated и ratio metrics с resampling по randomization unit, fixed RNG, paired
denominator handling и diagnostics.

## Цели обучения

- Ресемплить experiment observations по randomization unit, а не по событиям или заказам.
- Строить percentile bootstrap interval для proportions, means и ratio metrics.
- Сохранять paired numerator/denominator для ratio metrics.
- Использовать permutation test как sensitivity check к observed lift.
- Читать diagnostics: tiny sample, degenerate distribution, invalid denominator resamples
  и upstream decision readiness.

## Проблема

В `10/05` мы получили fixed-horizon effect table. Для revenue и refund этого мало:

```text
realized_revenue_per_user_7d: heavy tail и много нулей
refund_rate_7d: numerator и denominator живут парой
```

Наивный Welch interval для revenue в tiny был очень широким, а ratio metrics легко
сломать, если ресемплить numerator отдельно от denominator. Команда хочет простой ответ:

```text
А bootstrap подтверждает результат?
```

Честный ответ в этом уроке:

```text
Bootstrap дает sensitivity layer, но tiny sample остается tiny sample.
```

## Концепция

### Resampling unit - это design choice

Protocol объявляет:

```text
randomization_unit = user_id
analysis_unit = user_id
```

Значит bootstrap sample должен выбирать пользователей с возвращением внутри каждого
variant:

```text
control users    -> sample control users with replacement
treatment users  -> sample treatment users with replacement
statistic        -> treatment_statistic - control_statistic
repeat           -> 500 times with fixed RNG
```

Если ресемплить события, заказы или строки `orders`, мы меняем дизайн эксперимента и
создаем псевдоточность.

### Ratio metrics требуют paired denominator

Для `refund_rate_7d` observation хранит:

```text
user_id, numerator, denominator
U003,   1,         1
U001,   0,         0
U004,   0,         0
```

Bootstrap должен переносить пару `(numerator, denominator)` целиком. Нельзя независимо
семплировать refunded orders и paid orders: получится невозможная метрика.

В tiny control есть два пользователя с denominator `0`, поэтому часть bootstrap samples
имеет нулевой суммарный denominator. Артефакт не скрывает это:

```text
refund_rate_7d invalid_resamples = 148 / 500
diagnostics = invalid_denominator_resamples, paired_denominator_contains_zero_units
```

### Bootstrap interval не является решением

Для primary metric:

```text
observed lift = -0.666667
bootstrap CI = [-1.0, 0.0]
permutation p-value = 0.401198
```

Это не launch signal. Это sensitivity layer поверх уже известного вывода: primary
direction missed, observed sample ниже power plan, assumptions warning.

Для `paywall_to_trial_conversion_7d` bootstrap interval вырожден:

```text
bootstrap CI = [1.0, 1.0]
diagnostics = degenerate_bootstrap_distribution
```

Красивый interval здесь не означает уверенность. Он означает, что tiny sample слишком
мал и в treatment все две строки одинаковые.

## Соберите это

Откройте `outputs/experiment_bootstrap_analyzer.py`. Артефакт делает пять шагов.

### Шаг 1: прочитайте outputs из 10/05

Входы:

```text
metric_observations.csv
effect_results.csv
assumption_checks.json
```

Bootstrap не пересчитывает метрики из raw events. Он работает поверх уже проверенного
analysis table. Это защищает от расхождения между effect calculator и bootstrap layer.

### Шаг 2: проверьте resampling unit

В `outputs/bootstrap_spec.json`:

```json
{
  "resampling_unit": "user_id",
  "n_resamples": 500,
  "permutation_resamples": 500,
  "bootstrap_seed": 20260610
}
```

Артефакт проверяет, что `resampling_unit`, `analysis_unit` и `randomization_unit`
совпадают. Если заменить `user_id` на `session_id`, report станет invalid.

### Шаг 3: соберите bootstrap distribution

Для каждой metric:

```python
control_sample = sample(control_users, replace=True)
treatment_sample = sample(treatment_users, replace=True)
lift = statistic(treatment_sample) - statistic(control_sample)
```

Для proportions и means statistic - среднее `value`. Для ratio:

```python
statistic = sum(numerator) / sum(denominator)
```

### Шаг 4: посчитайте permutation sensitivity

Permutation check перемешивает variant labels при фиксированных group sizes:

```text
observed lift vs null lifts under label shuffle
```

Это не заменяет pre-registered test из `10/05`, но помогает увидеть, насколько observed
lift необычен без normal approximation assumptions.

### Шаг 5: сохраните manifest

`resampling_manifest.json` фиксирует:

```text
scipy_version
resampling_unit
bootstrap_seed
permutation_seed
n_resamples
paired_denominator_metrics
```

Без seed и manifest bootstrap не воспроизводим.

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/06-bootstrap/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "metrics_analyzed": 5,
  "distribution_rows": 2500,
  "primary_ci": [-1.0, 0.0],
  "refund_paired_denominator": true,
  "refund_invalid_resamples": 148
}
```

CLI артефакта:

```bash
uv run --locked python outputs/experiment_bootstrap_analyzer.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --bootstrap-spec outputs/bootstrap_spec.json \
  --observations ../05-means-and-proportions/outputs/metric_observations.csv \
  --effect-results ../05-means-and-proportions/outputs/effect_results.csv \
  --assumption-checks ../05-means-and-proportions/outputs/assumption_checks.json \
  --output-report /tmp/phase10-bootstrap-intervals.json \
  --output-distribution /tmp/phase10-bootstrap-distribution.csv \
  --output-manifest /tmp/phase10-resampling-manifest.json
```

## Сломайте это

Проверьте failure modes:

1. Поменяйте `resampling_unit` на `session_id`: artifact станет invalid, потому что
   experiment randomized по `user_id`.
2. Для `refund_rate_7d` ресемплите numerator и denominator отдельно: paired denominator
   contract будет нарушен.
3. Уберите users с denominator `0`: invalid resamples исчезнут, но вы измените target
   population ratio metric.
4. Уберите fixed seeds: committed `bootstrap_distribution.csv` перестанет
   воспроизводиться.
5. Прочитайте degenerate interval `[1.0, 1.0]` как сильную уверенность: это ошибка
   интерпретации tiny sample.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/06-bootstrap/tests -v
```

Они проверяют:

- committed bootstrap report, distribution и manifest совпадают с расчетом;
- primary interval воспроизводим и совпадает с effect table из `10/05`;
- `refund_rate_7d` сохраняет paired numerator/denominator и показывает invalid resamples;
- secondary trial/revenue signals остаются sensitivity, а не decision;
- все tiny metrics получают warning из-за малого sample;
- mismatch `resampling_unit` блокирует report;
- invalid upstream effect analysis блокирует bootstrap.

## Поставьте результат

Именованный артефакт:

```text
outputs/experiment_bootstrap_analyzer.py
outputs/bootstrap_spec.json
outputs/bootstrap_intervals.json
outputs/bootstrap_distribution.csv
outputs/resampling_manifest.json
```

`bootstrap_intervals.json` станет частью будущего `experiment-decision-package`: он
покажет bootstrap/permutation sensitivity, но не отменит primary/guardrail decision rule.

## Упражнения

1. Увеличьте `n_resamples` до `2000` и проверьте, какие intervals меняются, а какие
   остаются вырожденными.
2. Добавьте treatment refund order и посмотрите, как меняются `refund_rate_7d`
   invalid resamples и permutation p-value.
3. Перепишите statistic для `realized_revenue_per_user_7d` на median и объясните, почему
   это уже другой estimand.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Bootstrap | "Магический способ получить больше данных" | Resampling observed units with replacement для оценки uncertainty statistic |
| Resampling unit | "Любая строка таблицы" | Единица, которую можно считать независимой в дизайне; здесь `user_id` |
| Percentile interval | "Гарантированный confidence interval" | Квантили bootstrap distribution с assumptions и finite-sample limitations |
| Permutation test | "То же самое, что bootstrap" | Null-sensitivity через перестановку labels при фиксированных group sizes |
| Paired denominator | "Техническая деталь ratio" | Numerator и denominator должны переезжать вместе при resampling |
| Degenerate distribution | "Очень точный результат" | Resampling почти не меняет statistic; часто признак слишком маленького или однообразного sample |

## Дополнительное чтение

- [SciPy `bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) — официальный API для percentile/basic/BCa intervals, `paired`, `n_resamples` и `rng`.
- [SciPy `permutation_test`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) — официальный API для randomization/permutation tests и разных типов перестановок.
- [Efron, 1979, Bootstrap Methods: Another Look at the Jackknife](https://projecteuclid.org/journals/annals-of-statistics/volume-7/issue-1/Bootstrap-Methods-Another-Look-at-the-Jackknife/10.1214/aos/1176344552.full) — первичная статья о bootstrap; читать для понимания идеи resampling distribution.
- [Урок 09/06 Bootstrap](../../../09-applied-statistics/06-bootstrap/docs/ru.md) — внутреннее повторение percentile/basic/BCa intervals до применения в randomized experiment.
