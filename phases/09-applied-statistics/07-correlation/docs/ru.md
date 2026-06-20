# Корреляция и ложные связи

> Корреляция - это сигнал для проверки, а не лицензия на causal claim.

**Тип:** Build  
**Треки:** Product, ML  
**Пререквизиты:** `09-applied-statistics/06-bootstrap`  
**Время:** ~75 минут  
**Результат:** считает Pearson/Spearman correlations, stratified association и shuffled
controls, распознает Simpson-like reversal, common-cause segment effects и запрещает
причинные claims по наблюдательной связи.

## Цели обучения

- Считать Pearson и Spearman correlation на user-level sample.
- Проверять constant input и слишком маленькие strata.
- Сравнивать observed correlation с shuffled control.
- Видеть sign reversal между aggregate и stratified association.
- Машинно запрещать causal wording без causal design.

## Проблема

В sample видно:

```text
sessions_7d и activated_7d сильно связаны
```

Очень хочется написать:

```text
More sessions drive activation.
```

Но это наблюдательная таблица. Возможно, активированные пользователи сами чаще возвращаются.
Возможно, platform/device tier влияет и на sessions, и на activation. Возможно, sample
маленький. Поэтому артефакт урока выпускает не "инсайт", а audit: коэффициенты,
stratified checks, shuffled control и разрешенный тип claim.

## Концепция

### Pearson

Pearson r измеряет линейную связь:

```text
r = cov(x, y) / (sd(x) * sd(y))
```

Он чувствителен к выбросам и линейности.

### Spearman

Spearman считает Pearson correlation по рангам. Он лучше подходит для монотонных, но не
обязательно линейных связей.

### Stratified association

Aggregate correlation может поменять знак внутри сегмента. В tiny sample:

```text
aggregate onboarding_seconds vs activation: weak positive
high device_tier only: strong negative
mid device_tier: activation constant, correlation undefined
```

Это не доказывает Simpson's paradox в строгом учебниковом смысле, но достаточно для
warning: aggregate claim нельзя писать без стратификации.

## Соберите это

Ручная Pearson-формула:

```python
x_centered = [x_i - mean(x) for x_i in x]
y_centered = [y_i - mean(y) for y_i in y]
r = sum(a * b for a, b in zip(x_centered, y_centered)) / sqrt(sum(a*a) * sum(b*b))
```

Для shuffled control:

```python
for _ in range(n_shuffles):
    shuffled_y = rng.permutation(y)
    shuffled_r = corr(x, shuffled_y)
```

Затем считаем долю перестановок, где `abs(shuffled_r) >= abs(observed_r)`.

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/09-applied-statistics/07-correlation/outputs/correlation_auditor.py \
  --sample phases/09-applied-statistics/data/tiny/sample_observations.csv \
  --spec phases/09-applied-statistics/07-correlation/outputs/correlation_spec.json \
  --output-report phases/09-applied-statistics/07-correlation/outputs/correlation_audit.json
```

Короткий пример:

```bash
uv run --locked python phases/09-applied-statistics/07-correlation/code/main.py
```

Report содержит:

- `aggregate.pearson` и `aggregate.spearman`;
- `shuffled_control`;
- `strata`;
- `diagnostic_warning_ids`;
- `allowed_claim_type = association_only`.

## Сломайте это

1. Напишите в `candidate_claim`: `Long onboarding causes activation to increase`.

Ожидаемый check:

```text
onboarding_activation_by_device_tier_causal_wording_forbidden
```

2. Добавьте неизвестный method `magic`.

Ожидаемый check:

```text
correlation_methods_supported
```

3. Укажите несуществующую колонку `missing_sessions`.

Ожидаемый check:

```text
sessions_activation_columns_present
```

## Проверьте это

Запустите tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/09-applied-statistics/07-correlation/tests -v
```

Tests проверяют:

- aggregate Pearson/Spearman для sessions vs activation;
- shuffled control;
- stratified sign reversal и constant stratum warning;
- запрет causal wording;
- committed `correlation_audit.json` совпадает с runner output.

## Поставьте результат

Артефакт урока - `outputs/correlation_auditor.py`. Он выпускает
`outputs/correlation_audit.json`: машинный отчет, который можно приложить к statistical
evidence package. Главное ограничение в отчете: все claims остаются observational и
association-only.

## Упражнения

1. Добавьте association `support_tickets_7d` vs `activated_7d` и объясните, почему знак
   может быть контринтуитивным.
2. Замените `stratify_by` на `platform` и сравните warning ids.
3. Увеличьте `n_shuffles` и проверьте стабильность `extreme_rate`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Pearson correlation | Причинный эффект | Линейная association между двумя переменными |
| Spearman correlation | Более "истинная" корреляция | Rank-based монотонная association |
| Shuffled control | Новый estimator | Контроль после разрушения связи между x и y |
| Stratified reversal | Доказательство причины | Warning, что aggregate claim скрывает segment structure |
| Association-only claim | Слабый вывод | Честная формулировка для observational data |

## Дополнительное чтение

- [SciPy: `scipy.stats.pearsonr`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html) - коэффициент, p-value, confidence interval и warnings для constant input.
- [SciPy: `scipy.stats.spearmanr`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.spearmanr.html) - rank correlation и ограничения p-value для маленьких samples.
- [SciPy: `scipy.stats.permutation_test`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) - официальный путь к permutation logic, которую здесь уменьшили до shuffled control.
- [Pearl, Glymour, Jewell: Causal Inference in Statistics](https://bayes.cs.ucla.edu/PRIMER/) - почему association не равна causation и зачем нужен отдельный causal design.
