# Bootstrap

> Bootstrap начинается не с функции библиотеки, а с выбора единицы ресемплирования.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/05-confidence-intervals`  
**Время:** ~90 минут  
**Результат:** строит bootstrap distribution и intervals для произвольной statistic с
явной resampling unit, фиксированным RNG, paired mode, degenerate-data handling и
сравнением percentile/basic/BCa подходов.

## Цели обучения

- Выбирать `resampling_unit` до расчета.
- Строить bootstrap distribution для mean и median.
- Отличать percentile, basic и BCa intervals.
- Сохранять paired relationship между колонками user-level строки.
- Обнаруживать degenerate bootstrap distribution.

## Проблема

В `09/05` formula intervals показали слабое место: normal approximation для activation на
tiny sample покрывала true parameter хуже номинальных 95%. Для median onboarding formula
SE вообще был отложен в `09/03`.

Bootstrap дает практический путь:

```text
много раз ресемплируем пользователей с возвращением -> считаем statistic -> берем interval
по bootstrap distribution.
```

Но если ресемплировать не пользователей, а отдельные ячейки, мы разрушим grain. Поэтому
первое поле spec - не method, а `resampling_unit`.

## Концепция

### Resampling unit

Unit должен совпадать с тем, что считается независимой единицей анализа. В этой фазе это
`user_id`. Если у пользователя есть activation, onboarding duration и revenue, paired
bootstrap переносит всю строку вместе.

### Percentile interval

Берем quantiles bootstrap distribution:

```text
[q(alpha/2), q(1 - alpha/2)]
```

### Basic interval

Отражаем percentile interval вокруг observed statistic:

```text
[2 * estimate - q(1 - alpha/2), 2 * estimate - q(alpha/2)]
```

### BCa

BCa учитывает bias correction и acceleration. В этом уроке ручная реализация ограничена
percentile/basic, а BCa считается через `scipy.stats.bootstrap`.

## Соберите это

Для activation:

```python
values = [1, 1, 1, 0, 1]
indices = rng.integers(0, len(values), size=(n_resamples, len(values)))
bootstrap_samples = values[indices]
bootstrap_stats = bootstrap_samples.mean(axis=1)
```

Observed statistic:

```text
0.8
```

Percentile interval:

```python
lower, upper = np.quantile(bootstrap_stats, [0.025, 0.975])
```

Для median onboarding меняется только statistic:

```python
bootstrap_stats = np.median(bootstrap_samples, axis=1)
```

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/06-bootstrap/outputs/bootstrap_interval_builder.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --spec phases/09-applied-statistics/06-bootstrap/outputs/bootstrap_spec.json \
  --distribution-cards phases/09-applied-statistics/02-distributions/outputs/distribution_cards.json \
  --output-intervals phases/09-applied-statistics/06-bootstrap/outputs/bootstrap_intervals.json \
  --output-report phases/09-applied-statistics/06-bootstrap/outputs/bootstrap_report.json
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/06-bootstrap/code/main.py
```

Report содержит:

- `resampling_manifest`: unit, paired mode, seed, n_resamples;
- `intervals`: observed statistic, lower/upper, method, standard error;
- `distribution_summary`: min, quartiles, max и число уникальных bootstrap statistics.

## Сломайте это

1. Поставьте `method = magic_bootstrap`.

Ожидаемый check:

```text
bootstrap_methods_supported
```

2. Уберите distribution card `activation_7d`.

Ожидаемый check:

```text
activation_rate_percentile_distribution_card_resolves
```

3. Сделайте все activation values равными `true`.

Ожидаемый diagnostic:

```text
degenerate_bootstrap_distribution
```

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/06-bootstrap/tests -v
```

Tests проверяют:

- resampling manifest фиксирует `user_id`, paired mode и seed;
- percentile interval содержит observed statistic;
- basic interval работает для median;
- BCa идет через SciPy path;
- degenerate distribution возвращает warning, а не фальшивую precision;
- committed JSON совпадает с runner output.

## Поставьте результат

Артефакт урока - `outputs/bootstrap_interval_builder.py`. Он выпускает:

- `outputs/bootstrap_intervals.json` - интервалы по statistic id;
- `outputs/bootstrap_report.json` - manifest, checks и diagnostics.

Этот report нужен дальше: корреляция и регрессия не должны делать вид, что uncertainty уже
решена одним p-value или коэффициентом.

## Упражнения

1. Увеличьте `n_resamples` до `10000` и сравните стабильность bounds.
2. Добавьте statistic `support_tickets_7d` mean и проверьте, становится ли distribution
   degenerate.
3. Измените resampling unit на несуществующую колонку и добавьте check, который это
   запрещает.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Bootstrap distribution | Новые реальные данные | Распределение statistic по resamples из observed sample |
| Resampling unit | Любая строка файла | Единица, которую можно повторно выбирать без разрушения grain |
| Paired bootstrap | Bootstrap только для пар групп | Ресемплирование всей единицы анализа целиком |
| Percentile interval | Всегда лучший bootstrap interval | Quantile interval, простой и хрупкий при bias/skew |
| Degenerate bootstrap | Очень точный результат | Признак, что resampling не показывает uncertainty |

## Дополнительное чтение

- [SciPy: `scipy.stats.bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) - официальный API для percentile/basic/BCa intervals, `paired` и `rng`.
- [NumPy: Random Generator](https://numpy.org/doc/stable/reference/random/generator.html) - воспроизводимый RNG для ручного bootstrap distribution.
- [NumPy: `numpy.quantile`](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html) - quantile calculation для percentile и basic intervals.
- [NIST/SEMATECH e-Handbook: Bootstrap methods](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35a.htm) - обзор идеи resampling и bootstrap estimates.
