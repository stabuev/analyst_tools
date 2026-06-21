# Сегменты и неоднородные эффекты

> Сегментный lift не лечит проваленный эксперимент. Сначала pre-registration, overlap и
> cell size, потом интерпретация.

**Тип:** Case  
**Треки:** Product  
**Пререквизиты:** 10/09 - Подглядывание и последовательный анализ  
**Время:** ~75 минут  
**Результат:** анализирует predeclared segment effects, interaction checks, minimum cell
sizes и guardrail differences, помечает exploratory findings и не выдает post-hoc
subgroup lift за подтвержденный общий эффект.

## Цели обучения

- Разделить predeclared segment dimensions и post-hoc segment scans.
- Проверить, что внутри сегмента есть control и treatment, а cell sizes не ниже protocol.
- Отличить segment effect от interaction effect между сегментами.
- Пометить exploratory findings так, чтобы они не стали launch gate задним числом.
- Выпустить heterogeneity report, который дополняет, но не заменяет primary decision.

## Проблема

К концу `10/09` эксперимент уже не готов к запуску:

```text
primary gate не прошел
multiple-testing policy не разрешает launch
peeking audit нашел unplanned decision looks
```

Но в продуктовой встрече почти неизбежно появляется фраза:

```text
А если посмотреть по сегментам?
```

Это разумный вопрос, если команда хочет понять неоднородность эффекта. И это опасный
вопрос, если сегменты превращаются в способ выбрать красивый подрез после просмотра
данных.

В tiny-наборе есть три типа ситуаций:

```text
platform=android               есть обе ветки, но sample size смешной
acquisition_channel=paid_*     почти нет control внутри сегмента
country=RU                     post-hoc dimension, не predeclared launch gate
```

Правильный результат урока - не найти победивший сегмент, а доказать, что текущие
сегментные числа остаются диагностикой.

## Концепция

### Predeclared не значит automatically valid

В protocol заранее объявлены:

```json
"segment_policy": {
  "predeclared_dimensions": ["platform", "acquisition_channel"],
  "minimum_cell_size": 500,
  "post_hoc_segments_are_exploratory": true
}
```

Это дает право смотреть на `platform` и `acquisition_channel` как на заранее ожидаемые
разрезы. Но право смотреть не равно праву принимать решение. Для интерпретации нужны:

```text
обе ветки внутри сегмента
достаточный control cell size
достаточный treatment cell size
понятный interaction check
сохранение primary, guardrail, multiple-testing и peeking gates
```

### Missing variant ломает контраст

Если в `acquisition_channel=paid_search` есть только treatment, строка не является
оценкой эффекта:

```text
treatment mean - control mean
```

потому что control mean внутри этого сегмента отсутствует. Такой результат получает:

```text
status = missing_variant
p_value = nan
decision_eligible = false
```

### Minimum cell size защищает от красивого шума

В уроке `platform=android` имеет обе ветки:

```text
control_units = 3
treatment_units = 2
absolute_lift = -0.666667
```

Но protocol требует минимум `500` наблюдений в каждой ячейке. Поэтому строка остается:

```text
status = below_minimum_cell_size
```

Это не баг tiny-датасета, а учебная демонстрация: сегментный отчет должен явно показывать
границу надежности, а не прятать ее за p-value.

### Interaction - это сравнение эффектов, а не список lift

Segment effect отвечает:

```text
Какой treatment-control contrast внутри сегмента?
```

Interaction отвечает:

```text
Отличается ли effect в одном сегменте от effect в другом?
```

Для interaction check нужны хотя бы два сегмента, где внутри каждого есть обе ветки и
достаточные cell sizes. В нашем tiny-наборе этого нет, поэтому все interaction rows
получают:

```text
status = insufficient_overlap
```

### Post-hoc сегменты остаются exploratory

`country` не был predeclared dimension. Даже если `country=RU` можно посчитать как
число, отчет обязан сохранить:

```text
segment_role = post_hoc
decision_use = exploratory_only
decision_eligible = false
```

Такой результат можно использовать для следующей гипотезы или нового pre-registration,
но нельзя использовать как подтверждение текущего launch decision.

## Соберите это

Откройте `outputs/segment_effect_auditor.py`. Артефакт делает пять шагов.

### Шаг 1: загрузите protocol и upstream decision context

Auditor читает:

```text
10/01 experiment_protocol.json
10/05 metric_observations.csv
10/08 multiple_testing_report.json
10/09 sequential_monitoring_report.json
data/tiny/users.csv
10/10 segment_policy.json
```

Сегментный отчет не пересчитывает весь эксперимент. Он добавляет diagnostic layer поверх
уже построенного decision context.

### Шаг 2: проверьте segment policy

Policy должна быть согласована с protocol:

```text
predeclared dimensions subset protocol predeclared_dimensions
post-hoc dimensions outside protocol predeclared_dimensions
minimum_cell_size matches protocol
all dimensions exist in users
all metrics exist in observations
```

Если попробовать объявить `country` predeclared после просмотра данных, check
`predeclared_dimensions_match_protocol` станет invalid.

### Шаг 3: посчитайте segment rows

Для каждого `dimension`, `segment_value` и `metric_id` артефакт агрегирует:

```text
control_units
treatment_units
control_value
treatment_value
absolute_lift
p_value
diagnostics
```

Для долей используется `statsmodels.stats.proportion.proportions_ztest` как
production-проверка p-value. Но p-value считается только если внутри сегмента есть обе
ветки.

### Шаг 4: поставьте decision flags

Каждая строка получает явные флаги:

```text
has_both_variants
meets_minimum_cell_size
decision_eligible
decision_use
status
```

Даже predeclared строка не становится launch gate, если upstream gates не пройдены:

```text
multiple_testing_does_not_allow_launch
peeking_audit_not_ready_for_decision
```

### Шаг 5: проверьте interaction overlap

Interaction row строится по каждой паре `dimension + metric`. Если нет двух оцениваемых
сегментов с обеими ветками, строка получает:

```text
status = insufficient_overlap
diagnostics = ["need_at_least_two_segments_with_both_variants"]
```

Это лучше, чем молча сравнивать несравнимые категории.

## Используйте это

Запустите auditor из папки урока:

```bash
uv run --locked python outputs/segment_effect_auditor.py \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --segment-policy outputs/segment_policy.json \
  --observations ../05-means-and-proportions/outputs/metric_observations.csv \
  --users ../data/tiny/users.csv \
  --multiple-testing-report ../08-multiple-testing/outputs/multiple_testing_report.json \
  --peeking-report ../09-peeking/outputs/sequential_monitoring_report.json \
  --output-report outputs/heterogeneity_report.json \
  --output-segment-effects outputs/segment_effects.csv \
  --output-interactions outputs/interaction_checks.csv \
  --output-manifest outputs/segment_manifest.json
```

Ключевые числа:

```text
segment_rows = 13
missing_variant_rows = 10
below_minimum_cell_rows = 13
insufficient_interaction_checks = 5
```

Самая важная строка не та, где p-value выглядит интересно. Самая важная строка:

```text
segment_findings_not_launch_gates = true
```

Минимальный пример:

```bash
uv run --locked python code/main.py
```

Он печатает summary по `platform=android` и общие blockers.

## Сломайте это

Попробуйте три поломки.

1. В `segment_policy.json` поставьте `country` как `"predeclared": true`.
   Отчет станет invalid: post-hoc dimension нельзя легализовать задним числом.
2. Поставьте `"minimum_cell_size": 1`.
   Некоторые tiny-строки начнут выглядеть оцениваемыми, но policy перестанет совпадать с
   protocol.
3. Добавьте несуществующую метрику в policy.
   Check `segment_metrics_exist_in_observations` защитит отчет от тихого пропуска.

Хороший segment auditor должен падать на нарушении контракта, а не тихо выпускать
удобную таблицу.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

```text
committed outputs match recalculation
platform=android has both variants but below minimum cell size
acquisition_channel segments without one variant are not effects
country=RU stays exploratory_only
interaction checks require overlap in at least two segments
invalid policy cannot promote post-hoc country to predeclared
```

Если тест проходит, artifact можно использовать как защитный слой перед финальным
decision package.

## Поставьте результат

Именованный артефакт:

```text
outputs/segment_effect_auditor.py
```

Он выпускает:

```text
outputs/heterogeneity_report.json
outputs/segment_effects.csv
outputs/interaction_checks.csv
outputs/segment_manifest.json
```

Передавайте `heterogeneity_report.json` в `10/11`. Финальный decision protocol должен
читать этот отчет как диагностический input, а не как альтернативный способ принять
launch decision.

## Упражнения

1. Добавьте в policy `device_tier` как post-hoc dimension и объясните, какие строки
   получают `missing_variant`.
2. Сгенерируйте synthetic-набор, где два acquisition channels имеют обе ветки и cell size
   выше минимума, затем проверьте interaction p-value.
3. Расширьте auditor так, чтобы guardrail segment rows отличали `up_is_bad` от `up_is_good`
   и отдельно помечали segment-level guardrail risk.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Predeclared segment | Любой заранее упомянутый сегмент можно использовать для запуска | Сегмент можно анализировать, но он все равно обязан пройти overlap, cell size и decision gates |
| Post-hoc segment | Если p-value маленький, сегмент становится подтвержденным | Сегмент найден после просмотра данных и остается exploratory |
| Minimum cell size | Формальность в protocol | Минимальный размер каждой variant cell внутри сегмента для интерпретации |
| Missing variant | Сегмент с одним вариантом показывает сильный эффект | Без control и treatment внутри сегмента treatment-control contrast не определен |
| Interaction effect | Список segment lifts | Разница treatment effects между сегментами |

## Дополнительное чтение

- [statsmodels: proportions_ztest](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportions_ztest.html) - API, которым artifact проверяет p-value для двух долей внутри segment row.
- [Athey and Imbens: Recursive Partitioning for Heterogeneous Causal Effects](https://arxiv.org/abs/1504.01132) - первичный источник про неоднородные causal effects и риски поиска подгрупп.
- [Множественные проверки](../../08-multiple-testing/docs/ru.md) - вернитесь к family/gatekeeping логике, чтобы не превратить segment scan в cherry-picking.
- [Подглядывание и последовательный анализ](../../09-peeking/docs/ru.md) - проверьте, почему segment dashboard во время эксперимента может стать unplanned decision look.
