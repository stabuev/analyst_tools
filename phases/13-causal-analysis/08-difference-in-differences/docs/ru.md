# Difference-in-Differences

> DiD оценивает не «стало лучше после rollout», а насколько treated group изменилась
> сверх того, как изменилась бы без rollout при credible parallel trend.

**Тип:** Case  
**Треки:** Decision, Product  
**Пререквизиты:** 13/07 — Propensity weighting и doubly robust оценка  
**Время:** ~105 минут  
**Результат:** рассчитывает 2x2 и multi-period DiD для регионального rollout,
формулирует parallel-trends assumption, проверяет pre-trends и placebo periods и
распознает риск наивного TWFE при staggered adoption.

## Цели обучения

- Отличать before/after comparison от Difference-in-Differences.
- Собирать panel с grain `region_week` и проверять rollout calendar.
- Считать 2x2 DiD вручную по четырем cell means.
- Проверять not-yet-treated control, pre-trends, placebo period и composition placebo.
- Строить event-study table по event time и отмечать sparse tails.
- Сверять ручной DiD с saturated 2x2 regression.
- Считать full-panel TWFE coefficient и объяснять, почему при staggered adoption он
  остается diagnostic-only.
- Формулировать ограниченный causal claim только under assumptions.

## Проблема

Предыдущие уроки оценивали индивидуальный observational treatment:
`assisted_within_24h`. Теперь появляется другой дизайн: региональный rollout программы.

Данные фазы содержат:

```text
region_week_panel.csv
rollout_calendar.csv
```

Rollout идет волнами:

| Region | Rollout start |
|---|---|
| north | 2026-07-06 |
| south | 2026-07-20 |

Наивное чтение:

```text
north activation вырос после 2026-07-06, значит rollout помог
```

Проблема: activation мог бы расти и без rollout — сезонность, общий прогресс onboarding,
маркетинговая волна, изменение состава eligible users. DiD пытается отделить общий
временной сдвиг через control group, которая еще не получила rollout.

## Концепция

### 2x2 DiD — это second difference

Для двух групп и двух периодов:

```text
DiD =
  (Y_treated,post - Y_treated,pre)
  -
  (Y_control,post - Y_control,pre)
```

В уроке primary contrast:

```text
treated group = north
control group = south
pre window    = 2026-06-15..2026-06-29
post window   = 2026-07-06..2026-07-13
```

Почему post window заканчивается `2026-07-13`? Потому что south стартует `2026-07-20`.
До этого south — not-yet-treated control. После этого south уже treated, и comparison
перестает быть untreated counterfactual.

### Parallel trends — центральная предпосылка

DiD не требует одинакового уровня outcome до rollout. В данных north стабильно выше south:

```text
north pre mean = 0.47
south pre mean = 0.45
```

Но DiD требует, чтобы без rollout разница менялась бы параллельно:

```text
north pre slope ≈ south pre slope
```

В tiny data:

```text
north slope = 0.01 activation-rate points per week
south slope = 0.01 activation-rate points per week
slope difference ≈ 0
```

Это поддерживает assumption, но не доказывает ее. Ненаблюдаемый региональный shock после
rollout все еще может нарушить design.

### No anticipation и no spillovers

Еще две практические предпосылки:

- **No anticipation:** пользователи и команда региона не меняют поведение до active
  rollout week.
- **No spillovers:** rollout в north не меняет outcome в south до старта south rollout.

Если north уже делится специалистами, маркетинговым трафиком или продуктовым UI с south,
south может перестать быть хорошим control.

### Event study показывает динамику, но не магию

Event time:

```text
event_time_weeks = (week_start - rollout_start) / 7
```

Reference event time в уроке:

```text
-1
```

Event-study table показывает outcome относительно этого reference period. В balanced
window `[-3, 2]` есть оба региона; в tails `[-5, -4, 3, 4]` только один регион, поэтому
artifact делает warning:

```text
event_study_sparse_tails_are_visible
```

Красивый event-study chart без пометки sparse tails легко вводит в заблуждение.

### TWFE — удобная сверка, но не всегда primary estimator

Full-panel TWFE:

```text
activation_rate_14d ~ rollout_active + region fixed effects + week fixed effects
```

В tiny data coefficient равен `0.08`, как и primary manual DiD. Но artifact всё равно
помечает TWFE как diagnostic-only:

```text
twfe_is_diagnostic_only_for_staggered_adoption
```

Причина: при staggered adoption наивный TWFE может сравнивать later-treated cohorts с
already-treated cohorts и смешивать dynamic treatment effects с весами когорт. В этой
маленькой синтетике эффект одинаковый, поэтому число совпало; в реальной работе это не
гарантировано.

## Соберите это

Артефакты урока:

```text
outputs/did_spec.json
outputs/did_analyzer.py
outputs/did_report.json
```

### Шаг 1: проверьте panel grain и rollout calendar

Исходный panel:

```text
region_id + week_start -> one row
```

Artifact проверяет:

- нет duplicate `region_id, week_start`;
- в `rollout_calendar.csv` один rollout row на регион;
- `rollout_active` совпадает с `rollout_start` и `rollout_end`;
- scenario `regional_did` есть в `causal_scenarios.csv`.

Если `south` пометить active на `2026-07-13`, report станет invalid: calendar говорит,
что south стартует только `2026-07-20`.

### Шаг 2: посчитайте четыре cell means

Primary cell table:

| Group | Period | Weeks | Mean activation |
|---|---|---:|---:|
| north | pre | 3 | 0.470 |
| north | post | 2 | 0.575 |
| south | pre | 3 | 0.450 |
| south | post | 2 | 0.475 |

Ручной расчет:

```text
treated change = 0.575 - 0.470 = 0.105
control change = 0.475 - 0.450 = 0.025
DiD estimate   = 0.105 - 0.025 = 0.080
```

Интерпретация:

```text
Under stated assumptions, early north rollout is associated with
+8.0 percentage points activation-rate lift versus not-yet-treated south.
```

Слово `associated` здесь не случайное: causal wording разрешен только в форме “under
assumptions”, а не “proved”.

### Шаг 3: сверка saturated 2x2 regression

Для selected 2x2 rows artifact строит:

```text
Y ~ treated_group + post_period + treated_group:post_period
```

Interaction coefficient:

```text
0.08000000000000013
```

Он совпадает с ручным DiD. Это полезная сверка, но не обязательная магия: вся causal
логика была в выборе groups/windows и assumptions, а не в OLS API.

### Шаг 4: pretrend и placebo checks

Pretrend:

```text
north slope = 0.01
south slope = 0.01
slope difference ≈ 0
```

Placebo fake rollout:

```text
fake post = 2026-06-29
placebo DiD = 0.0
```

Composition placebo:

```text
outcome = mean_friction_score
DiD ≈ 0.0
```

Если placebo не проходит, limited causal claim блокируется. Artifact не делает вид, что
“число есть — значит вывод готов”.

### Шаг 5: event-study table

Фрагмент table:

| Event time | Regions | Mean outcome | Relative to -1 |
|---:|---|---:|---:|
| -3 | north, south | 0.46 | -0.02 |
| -2 | north, south | 0.47 | -0.01 |
| -1 | north, south | 0.48 | 0.00 |
| 0 | north, south | 0.57 | 0.09 |
| 1 | north, south | 0.58 | 0.10 |
| 2 | north, south | 0.59 | 0.11 |

Sparse tails:

```text
-5, -4, 3, 4
```

Их можно показать на графике, но нельзя интерпретировать так же уверенно, как balanced
window.

## Используйте это

Запуск из корня репозитория:

```bash
python phases/13-causal-analysis/08-difference-in-differences/outputs/did_analyzer.py
```

Скрипт обновляет:

```text
phases/13-causal-analysis/08-difference-in-differences/outputs/did_report.json
```

Короткий пример:

```bash
python phases/13-causal-analysis/08-difference-in-differences/code/main.py
```

Ожидаемые поля:

```json
{
  "did_valid": true,
  "treated_change": 0.105,
  "control_change": 0.025,
  "did_estimate": 0.08,
  "twfe_coefficient": 0.08,
  "fake_pre_placebo_did": 0.0,
  "effect_claim_allowed": true
}
```

Для CI:

```bash
python phases/13-causal-analysis/08-difference-in-differences/outputs/did_analyzer.py \
  --fail-on-invalid
```

Warnings не ломают report, но должны попасть в интерпретацию:

```text
event_study_sparse_tails_are_visible
twfe_is_diagnostic_only_for_staggered_adoption
```

## Сломайте это

### Control becomes treated

Если расширить primary post window до `2026-07-20`, south уже active. Check:

```text
primary_control_is_not_yet_treated_in_post_window
```

становится blocking error.

### Broken rollout calendar

Если в panel поставить `south rollout_active = true` на `2026-07-13`, calendar check
сработает:

```text
rollout_active_matches_calendar
```

### Failed pretrend

Если поднять south activation в последнюю pre-period week, slope difference станет
слишком большой:

```text
parallel_pretrend_slope_check_passes = false
claim_policy_requires_passing_design_assumptions = false
```

### Failed placebo

Если fake pre-period rollout дает non-zero DiD, limited effect claim тоже блокируется.

### Naive late cohort comparison

Candidate:

```text
south_late_vs_north_already_treated
```

rejected как:

```text
invalid_already_treated_control
```

North уже treated во время south pre-window; это не untreated counterfactual.

## Проверьте это

Поведенческие тесты:

```bash
python -m unittest phases/13-causal-analysis/08-difference-in-differences/tests/test_main.py
```

Покрытие:

- primary 2x2 DiD numbers;
- code example summary;
- four-cell manual accounting;
- saturated 2x2 regression reconciliation;
- pretrend slopes и placebo checks;
- event-study reference period и sparse tails;
- TWFE coefficient и diagnostic-only warning;
- candidate design status policy;
- invalid control already treated in post window;
- duplicate region-week grain;
- rollout calendar mismatch;
- failed pretrend/placebo blocking claim policy;
- scenario registry alignment;
- CLI `--fail-on-invalid`.

## Поставьте результат

Именованный artifact:

```text
did-rollout-analyzer
```

Файлы:

```text
outputs/did_analyzer.py
outputs/did_spec.json
outputs/did_report.json
outputs/artifact.json
```

Handoff-фраза:

```text
Primary early-rollout 2x2 DiD estimates +8.0 percentage points activation-rate lift
for north versus not-yet-treated south. Pretrend and placebo checks pass on tiny data.
Event-study tails are sparse and full-panel TWFE is diagnostic-only because adoption is
staggered. Causal wording is limited to the stated parallel-trends/no-anticipation/
stable-composition/no-spillover assumptions.
```

## Упражнения

1. Расширьте primary post window до `2026-07-20`. Какой check блокирует design?
2. Поменяйте `reference_event_time` на `-2`. Как изменится `relative_to_reference` в
   event-study table?
3. Добавьте third region в panel как never-treated control. Как изменится sparse-tail
   warning и TWFE risk?
4. Сделайте placebo outcome по `paid_subscription_rate_30d`. Почему он хуже как placebo,
   чем `mean_friction_score`?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| DiD | «Просто сравнить before/after у treated» | Difference between treated change and control change |
| Parallel trends | «До rollout уровни outcome одинаковые» | Без treatment изменения outcome были бы параллельными |
| Not-yet-treated control | «Любой регион без текущего treatment в конкретную неделю» | Cohort, который еще не получил rollout и может служить contemporaneous untreated comparison |
| Event study | «Автоматическое доказательство эффекта по неделям» | Динамика outcome относительно event time и reference period, чувствительная к sparse tails |
| TWFE | «Универсальная DiD-регрессия» | Fixed-effects reconciliation, который при staggered adoption может смешивать already-treated controls и dynamic effects |
| Placebo check | «Доказательство assumptions» | Falsification check, который может опровергнуть design, но не доказать counterfactual trend |

## Дополнительное чтение

- [Card and Krueger, 1994](https://davidcard.berkeley.edu/papers/njmin-aer.pdf) — классический DiD-пример; полезно читать как дизайн сравнения, а не как универсальный шаблон.
- [Bertrand, Duflo and Mullainathan, 2004](https://doi.org/10.1162/003355304772839588) — почему DiD standard errors и serial correlation нельзя игнорировать в реальных panel data.
- [Goodman-Bacon, 2021](https://doi.org/10.1016/j.jeconom.2021.03.014) — decomposition TWFE при variation in treatment timing; источник главного предупреждения про staggered adoption.
- [Callaway and Sant'Anna, 2021](https://doi.org/10.1016/j.jeconom.2020.12.001) — group-time average treatment effects как современная альтернатива наивному TWFE при staggered treatment.
- [statsmodels OLS documentation](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLS.html) — API, с которым artifact сверяет ручной dummy-matrix TWFE coefficient.
