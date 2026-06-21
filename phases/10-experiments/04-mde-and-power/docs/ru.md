# MDE, мощность и размер выборки

> Эксперимент без power plan может быть дорогим способом получить "непонятно".

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/03 - A/A-тест и Sample Ratio Mismatch  
**Время:** ~90 минут  
**Результат:** рассчитывает baseline, MDE, power, alpha, allocation ratio, expected
traffic и runtime для долей и средних, сравнивая formula-based calculation с симуляцией
мощности.

## Цели обучения

- Отличать baseline, MDE, alpha, power, sample size и runtime.
- Рассчитывать sample size для proportion primary metric.
- Рассчитывать sample size для mean metric с заданной standard deviation.
- Строить MDE grid и power curve для planned sample.
- Блокировать sizing, если upstream randomization health не готов к A/B-анализу.

## Проблема

В `10/01` команда зафиксировала primary metric `activation_rate_7d`, MDE `+3 п.п.`,
alpha `0.05` и power `0.8`. В `10/02` появились stable assignments, в `10/03` — health
gate. Теперь нужно ответить на практический вопрос:

```text
Сколько пользователей нужно на вариант и сколько дней держать эксперимент?
```

Плохой ответ выглядит так:

```text
Запустим на неделю. Если p-value не пройдет, значит эффекта нет.
```

Такой план смешивает отсутствие эффекта с отсутствием мощности. Если sample слишком мал,
эксперимент может быть inconclusive даже при practically important lift. Если MDE выбран
после результата, команда подгоняет критерий под увиденное число.

## Концепция

### Baseline и MDE задают размер задачи

Baseline — ожидаемое значение метрики в control. В уроке:

```text
activation_rate_7d baseline = 0.30
```

MDE — минимальный practically important эффект, который команда хочет обнаружить:

```text
absolute MDE = 0.03
relative MDE = 0.03 / 0.30 = 10%
```

Если MDE слишком маленький, нужен огромный sample. Если MDE слишком большой, эксперимент
может пропустить полезный, но меньший эффект.

### Power отвечает на вопрос "увидим ли объявленный эффект"

Power `0.8` означает: если истинный эффект равен MDE, выбранный test и sample size
обнаружат его примерно в 80% повторов. Это не вероятность, что текущий эксперимент
успешен, и не гарантия positive result.

В fixed-horizon дизайне заранее фиксируются:

```text
alpha
power
MDE
allocation ratio
expected traffic
minimum runtime
```

### Runtime ограничивается не только sample size

Для primary metric артефакт считает:

```text
required_n_per_variant = 2964
required_total_units = 5928
expected_daily_eligible_units = 1800
runtime_days_unconstrained = ceil(5928 / 1800) = 4
minimum_runtime_days = 14
recommended_runtime_days = 14
```

Даже если traffic набирается быстро, protocol может требовать минимум 14 дней: нужно
покрыть metric windows, календарные эффекты и pre-registered stopping rule.

### Formula и simulation проверяют друг друга

Формула через `statsmodels` дает быстрый расчет. Симуляция повторяет эксперимент много
раз и проверяет, что рассчитанный sample действительно дает мощность около target.

В уроке:

| Metric | Formula required n per variant | Simulation power at required n |
|---|---:|---:|
| `activation_rate_7d` | 2964 | 0.79615 |
| `realized_revenue_per_user_7d` | 7123 | 0.804333 |

Simulation не заменяет формулу, но ловит грубые ошибки в effect size, alternative,
allocation или denominator.

## Соберите это

Откройте `outputs/power_planner.py`. Артефакт делает четыре вещи.

### Шаг 1: проверьте upstream health gate

Power plan имеет смысл только если `randomization_health_report.json` готов к A/B:

```json
{
  "ready_for_ab_analysis": true,
  "summary": {
    "blocking_failures": []
  }
}
```

Если upstream health invalid, planner возвращает non-zero exit code и не выпускает
metric plans. Это не статистическая тонкость, а защита от планирования поверх сломанного
pipeline.

### Шаг 2: рассчитайте proportion effect size

Для primary metric:

```python
effect_size = proportion_effectsize(treatment_rate, control_rate)
required_n = NormalIndPower().solve_power(
    effect_size=abs(effect_size),
    alpha=0.05,
    power=0.8,
    ratio=1.0,
    alternative="larger",
)
```

При baseline `0.30` и treatment rate `0.33` результат:

```text
required_n_control = 2964
required_n_treatment = 2964
```

### Шаг 3: рассчитайте mean metric

Для `realized_revenue_per_user_7d` в spec зафиксирована sizing assumption:

```text
baseline mean = 42.50
standard deviation = 120.0
MDE = 5.0
effect_size = 5.0 / 120.0 = 0.041667
```

Артефакт использует `TTestIndPower` и получает:

```text
required_n_per_variant = 7123
planned_power at 12000 per variant = 0.943237
```

Это не финальный revenue analysis. Для skewed revenue позже будет bootstrap (`10/06`).
Здесь mean metric нужен как sizing example с явной dispersion assumption.

### Шаг 4: постройте MDE grid

`outputs/mde_grid.csv` показывает trade-off:

```text
MDE +1 п.п. -> 26210 users per variant
MDE +2 п.п. ->  6611 users per variant
MDE +3 п.п. ->  2964 users per variant
MDE +4 п.п. ->  1681 users per variant
MDE +5 п.п. ->  1084 users per variant
```

Это помогает обсудить не только "сколько ждать", но и "какой эффект стоит бизнес-решения".

## Используйте это

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/04-mde-and-power/code/main.py
```

Фрагмент результата:

```json
{
  "valid": true,
  "primary_required_n_per_variant": 2964,
  "primary_planned_power": 0.999609,
  "revenue_required_n_per_variant": 7123,
  "recommended_runtime_days": 14,
  "grid_rows": 5
}
```

CLI артефакта:

```bash
uv run --locked python outputs/power_planner.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --metric-baselines ../data/tiny/metric_baselines.csv \
  --health-report ../03-aa-and-srm/outputs/randomization_health_report.json \
  --power-spec outputs/power_spec.json \
  --output-plan /tmp/phase10-power-plan.json \
  --output-grid /tmp/phase10-mde-grid.csv \
  --output-figure /tmp/phase10-power-curve.png
```

Команда печатает `power_plan.json`. Если planned sample underpowered или upstream health
gate invalid, CLI возвращает `1`.

## Сломайте это

Проверьте отдельные failure modes:

1. Поставьте `planned_units_per_variant = 500`: plan станет invalid, потому что planned
   power ниже target.
2. Поставьте `ready_for_ab_analysis = false` в health report: planner заблокирует sizing.
3. Уберите baseline для primary metric: planner не сможет рассчитать effect size.
4. Задайте MDE, при котором treatment proportion выходит за `1.0`: planner остановится
   до красивого, но бессмысленного числа.
5. Поставьте `baseline_standard_deviation = 0`: mean sizing заблокируется.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/04-mde-and-power/tests -v
```

Они проверяют:

- committed `power_plan.json` совпадает с расчетом;
- primary proportion sizing дает `2964` users per variant;
- mean metric sizing дает `7123` users per variant;
- MDE grid монотонен и совпадает с committed CSV;
- upstream health gate блокирует sizing;
- underpowered planned sample помечает metric как `underpowered`;
- CLI пишет JSON, CSV и PNG;
- code example печатает sizing summary.

## Поставьте результат

Именованный артефакт:

```text
outputs/power_planner.py
outputs/power_spec.json
outputs/power_plan.json
outputs/mde_grid.csv
outputs/power_curve.png
```

`power_plan.json` становится частью будущего `experiment-decision-package`: он фиксирует,
какой эффект experiment мог обнаружить и почему итоговый neutral result может быть
`inconclusive`, а не "эффекта нет".

## Упражнения

1. Измените primary MDE с `0.03` на `0.02` и объясните, почему sample вырос с `2964` до
   `6611` users per variant.
2. Поменяйте allocation ratio на `2:1` в пользу treatment и сравните total required units.
3. Увеличьте standard deviation revenue metric до `180.0` и пересчитайте mean sizing.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Baseline | "Любое прошлое значение метрики" | Control expectation, от которого считается detectable effect |
| MDE | "Прогноз будущего lift" | Минимальный practically important effect для планирования мощности |
| Power | "Вероятность, что treatment победит" | Вероятность обнаружить заданный эффект при альтернативе |
| Alpha | "Порог качества продукта" | Допустимая вероятность false positive при null hypothesis |
| Runtime | "Сколько дней нужно, чтобы набрать sample" | Срок, ограниченный traffic, metric windows, календарем и pre-registered policy |
| Effect size | "То же самое, что absolute lift" | Нормированная величина эффекта, которую использует статистическая формула |

## Дополнительное чтение

- [statsmodels `NormalIndPower`](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.NormalIndPower.html) — официальный API для power и sample-size расчетов по нормальной аппроксимации двух независимых долей.
- [statsmodels `proportion_effectsize`](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_effectsize.html) — официальный helper для effect size по двум proportions; именно он переводит baseline/MDE в scale solver-а.
- [statsmodels `TTestIndPower`](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.html) — официальный API для sizing двух независимых средних при t-test assumptions.
- [SciPy `ttest_ind`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html) — официальный API, который полезен для simulation sanity check mean metrics и понимания `alternative`.
