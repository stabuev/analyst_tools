# A/A-тест и Sample Ratio Mismatch

> До вопроса "какой вариант лучше" идет вопрос "похоже ли это на честно наблюдаемый эксперимент".

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/02 - Единица рандомизации  
**Время:** ~90 минут  
**Результат:** проводит A/A-test, SRM check и randomization validation: сверяет expected
allocation, variant counts, covariate balance, telemetry loss и metric null distribution
до анализа A/B.

## Цели обучения

- Отличать randomization health checks от оценки treatment effect.
- Считать Sample Ratio Mismatch по assignment и exposure counts.
- Проверять telemetry loss между assignment и exposure logs.
- Использовать pre-treatment covariates как A/A pseudo-outcomes.
- Разделять blocking failures и warning-level diagnostics в machine-readable report.

## Проблема

После `10/02` у команды есть стабильные assignments и exposures. Можно было бы сразу
считать `activation_rate_7d`, но это опасный shortcut. Если до анализа эффекта не
проверить качество рандомизации и логов, результат может выглядеть статистически
аккуратно и при этом отвечать на сломанную выборку.

Типичные дефекты:

```text
assignment split не совпал с 50/50 allocation
treatment exposures потерялись из telemetry
pre-treatment covariates сильно отличаются между вариантами
A/A на pre-period метрике показывает невозможный "эффект"
```

SRM и A/A не говорят, что treatment плохой или хороший. Они говорят, можно ли доверять
дизайну и данным перед тем, как считать treatment effect.

## Концепция

### SRM проверяет traffic allocation, а не outcome

Sample Ratio Mismatch возникает, когда observed counts по вариантам заметно расходятся с
expected allocation:

```text
expected 50/50
observed 70/30
```

Причины могут быть разными: routing bug, eligibility drift, feature-flag condition,
client crash, identity stitching или потеря событий. Поэтому в уроке есть две проверки:

| Проверка | Что считает | Какой дефект ищет |
|---|---|---|
| `assignment_srm_chi_square` | variant counts в `assignments.csv` | routing или assignment defect |
| `exposure_srm_chi_square` | variant counts в `exposures.csv` | потеря exposure событий или biased logging |

Если assignment SRM чистый, а exposure SRM или telemetry loss плохие, проблема не в
hash bucket, а в наблюдаемости события влияния.

### Chi-square SRM - это gate, а не эффект

Для двух вариантов с allocation 50/50:

```text
expected_control = total * 0.5
expected_treatment = total * 0.5
chi_square = sum((observed - expected)^2 / expected)
```

Protocol `10/01` задает строгий `srm_alpha = 0.001`. В production SRM должен быть редким:
если он случился, анализ блокируется до расследования. На tiny-profile всего пять
assigned users, поэтому split 3/2 дает:

```text
chi_square = 0.2
p_value = 0.654721
```

Это не SRM, а нормальная дискретность маленького учебного набора.

### Telemetry loss может имитировать SRM после assignment

Assignment может быть честным, но exposure logs могут потеряться. В уроке diagnostic
считает:

```text
assigned units
exposed units
missing exposures
missing rate by variant
variant missing-rate gap
extra exposure units
duplicate exposure units
```

Если treatment exposures теряются чаще control, denominator будущей метрики уже смещен.
Это blocking failure, даже если assignment buckets были стабильны.

### A/A на pre-period metrics ищет невозможный сигнал

В настоящем A/A оба варианта одинаковые. В этом уроке мы используем pre-treatment metrics
как pseudo-outcomes: treatment еще не мог повлиять на `sessions_7d_pre`,
`activation_7d_pre`, support tickets или revenue до эксперимента. Если split уже там
показывает сильный сигнал, нужно проверить randomization и population.

Артефакт считает exact two-sided permutation p-value для разницы средних. Для tiny
profile p-values не блокируют анализ, но report показывает warning по standardized mean
differences: пять users недостаточны, чтобы covariate balance выглядел как production.

## Соберите это

Откройте `outputs/randomization_health.py`. Механизм состоит из четырех блоков.

### Шаг 1: посчитайте expected counts

Traffic allocation берется из protocol:

```json
{
  "control": 0.5,
  "treatment": 0.5
}
```

Для пяти assignments expected counts равны `2.5` и `2.5`. Observed counts в baseline:

```json
{
  "control": 3,
  "treatment": 2
}
```

### Шаг 2: проверьте SRM через chi-square

Артефакт использует `scipy.stats.chisquare`:

```python
statistic, p_value = stats.chisquare(
    f_obs=[observed["control"], observed["treatment"]],
    f_exp=[expected["control"], expected["treatment"]],
)
```

Если `p_value < srm_alpha`, check становится blocking error. В baseline:

```text
assignment_srm_chi_square: p_value = 0.654721
exposure_srm_chi_square:   p_value = 0.654721
```

### Шаг 3: сравните assignment и exposure units

Telemetry block строится без статистики:

```text
missing_units = assigned_units - exposed_units
extra_units = exposed_units - assigned_units
missing_rate_by_variant = missing / assigned
```

В baseline все пять assigned users имеют exposure. Если удалить treatment exposures,
report вернет non-zero exit code и check `telemetry_loss_by_variant` станет invalid.

### Шаг 4: проверьте pre-treatment pseudo-outcomes

Для каждой pre-period метрики diagnostic делит значения по variant и считает exact
permutation p-value. На tiny-profile для `sessions_7d_pre`:

```text
control mean = 2.0
treatment mean = 4.5
observed difference = 2.5
p_value = 0.2
permutations = 10
```

Это не treatment effect. Это sanity check: сигнал до treatment был бы подозрительным.

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/03-aa-and-srm/code/main.py
```

Фрагмент результата:

```json
{
  "ready_for_ab_analysis": true,
  "assignment_srm_p_value": 0.654721,
  "exposure_srm_p_value": 0.654721,
  "telemetry_missing_units": 0,
  "warning_checks": [
    "covariate_balance_standardized_difference"
  ]
}
```

CLI артефакта:

```bash
uv run --locked python outputs/randomization_health.py \
  --assignments ../data/tiny/assignments.csv \
  --exposures ../data/tiny/exposures.csv \
  --pre-metrics ../data/tiny/pre_experiment_metrics.csv \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --health-spec outputs/randomization_health_spec.json \
  --output /tmp/phase10-randomization-health.json
```

Если есть blocking failures, CLI возвращает `1`. Warning-level checks попадают в report,
но не блокируют `ready_for_ab_analysis`.

## Сломайте это

Проверьте, что diagnostic различает типы поломок:

1. Все 100 synthetic assignments попали в control: `assignment_srm_chi_square` блокирует
   анализ.
2. Из exposure logs исчезли treatment users: `telemetry_loss_by_variant` блокирует
   анализ.
3. Exposure появился для unknown assignment unit: `extra_exposure_units` становится
   blocking failure.
4. Нет pre-treatment metric row для assigned user: `pre_experiment_metrics_complete`
   блокирует A/A checks.
5. В pre-period pseudo-outcome treatment уже выглядит экстремально лучше control:
   `aa_pre_experiment_pseudo_outcomes` становится warning.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/03-aa-and-srm/tests -v
```

Они проверяют:

- committed `randomization_health_report.json` совпадает с расчетом;
- baseline готов к A/B-анализу, но содержит warning по tiny covariate balance;
- exact permutation A/A p-values воспроизводимы;
- code example печатает health summary;
- extreme large split блокируется как SRM;
- telemetry loss и extra exposure unit блокируют report;
- missing pre-treatment rows/columns блокируют report;
- CLI пишет report и возвращает non-zero при blocking telemetry loss.

## Поставьте результат

Именованный артефакт:

```text
outputs/randomization_health.py
outputs/randomization_health_spec.json
outputs/randomization_health_report.json
```

Этот report становится upstream gate для `10/04`-`10/05`: планировать мощность и считать
effect можно только после того, как assignment/exposure health прошел blocking checks.

## Упражнения

1. Поменяйте `srm_alpha` на `0.05` и объясните, почему production gate обычно строже.
2. Удалите один control exposure и сравните assignment SRM, exposure SRM и telemetry-loss
   check.
3. Добавьте в `pre_experiment_metrics.csv` ковариату `days_since_registration_pre` и
   включите ее в `randomization_health_spec.json`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Sample Ratio Mismatch | "Treatment хуже, потому что пользователей меньше" | Несовпадение observed variant counts с expected allocation |
| A/A-test | "Бесполезный A/B без treatment" | Health check, где ожидается отсутствие сигнала между одинаковыми вариантами |
| Telemetry loss | "Просто меньше строк" | Потеря событий, которая может смещать denominator и outcome, особенно если зависит от variant |
| Pre-treatment covariate | "Любая метрика до отчета" | Метрика, измеренная до exposure и не являющаяся следствием варианта |
| Blocking failure | "Любое предупреждение" | Дефект, после которого A/B-effect нельзя интерпретировать до расследования |

## Дополнительное чтение

- [SciPy `chisquare`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chisquare.html) — официальный API, который используется для SRM chi-square проверки expected allocation.
- [SciPy `permutation_test`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) — официальный API для permutation-based tests; сравните его с ручным exact permutation в уроке.
- [Ensure A/B Test Quality at Scale with Automated Randomization Validation and Sample Ratio Mismatch Detection](https://arxiv.org/abs/2208.07766) — primary source про automated randomization validation и SRM detection на масштабе платформы экспериментов.
- [Trustworthy Experimentation Under Telemetry Loss](https://arxiv.org/abs/1903.12470) — primary source о том, почему потеря telemetry может смещать экспериментальные выводы.
