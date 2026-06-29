# Matching и баланс ковариат

> Matching не делает observational study экспериментом; он показывает, кого вообще
> можно честно сравнивать.

**Тип:** Build  
**Треки:** Decision, Product  
**Пререквизиты:** 13/05 — Regression adjustment и g-formula  
**Время:** ~90 минут  
**Результат:** строит matching по pre-treatment covariates, задает caliper и replacement
policy, проверяет common support, standardized mean differences и изменение target
population после отбора.

## Цели обучения

- Отличать full target-population ATE от matched ATT в common-support subset.
- Строить nearest-neighbor matching по pre-treatment distance.
- Объяснять, зачем нужны caliper, replacement и tie-breaker.
- Считать standardized mean differences до и после matching.
- Выпускать love plot data как машинный balance artifact.
- Блокировать matching по mediator, collider, selection variable и outcome leakage.
- Интерпретировать unmatched treated users как evidence about positivity, а не как
  «технический мусор».

## Проблема

В `13/05` мы получили regression-adjusted g-computation estimate. Это был первый
прозрачный estimator, но он опирался на outcome model и extrapolation warnings.

Теперь бизнес задает естественный вопрос:

```text
А можно просто сравнить похожих пользователей?
```

Можно — но слово «похожих» должно быть операциональным:

- похожих по каким pre-treatment признакам;
- насколько близко — то есть какой distance и caliper;
- можно ли использовать одного control несколько раз;
- что делать с treated users, для которых нет похожего control;
- стала ли matched population той же самой population, что исходный estimand.

Главная ошибка: запустить matching, получить красивое число и сказать «теперь bias
исчез». Matching проверяет observed balance. Он не доказывает exchangeability и не
удаляет `latent_motivation`, который уже отмечен в `13/03` и `13/04`.

## Концепция

### Matching меняет вопрос, если часть treated не матчится

Исходный estimand из `13/01` — ATE по eligible high-friction population:

```text
E[Y(assisted) - Y(no_assistance) | eligible_high_friction_users]
```

Nearest-neighbor matching чаще отвечает на более узкий вопрос:

```text
ATT among treated users with acceptable control neighbors
```

Если high-risk treated users выпали из common support, matched estimate уже не
представляет весь target population. Это не провал урока, а важный результат: данные не
поддерживают сравнение в этой зоне.

### Distance должен использовать только pre-treatment information

В этом уроке primary matching design использует standardized Euclidean distance по двум
pre-treatment features:

```text
friction_score
specialist_capacity
```

Обе переменные доступны до treatment и участвуют в assignment mechanism. Для balance
audit дополнительно проверяется compact `baseline_risk_score` из `13/05` и
`activation_14d_pre`.

Запрещено использовать:

- `onboarding_completed_48h` — mediator total effect;
- `opened_support_chat_after_offer` — possible collider;
- `telemetry_complete_30d` — selection variable;
- `activation_14d` или `paid_subscription_30d` — outcome/downstream leakage.

### Caliper защищает от forced bad matches

Nearest neighbor без caliper всегда найдет «лучшего» control. Но лучший из плохих
соседей может быть всё равно плохим.

В tiny data используется:

```json
{
  "distance_metric": "standardized_euclidean",
  "distance_features": ["friction_score", "specialist_capacity"],
  "caliper": 1.5,
  "replacement": true,
  "ratio": 1
}
```

Если nearest distance больше `1.5`, treated user остается unmatched. Это честнее, чем
насильно притянуть distant control и спрятать positivity violation.

### Replacement снижает bias, но меняет effective control diversity

С replacement один control может матчиться к нескольким treated. Это полезно при малом
числе comparators, но effective number of controls уменьшается.

В tiny report `U005` используется дважды. Поэтому artifact явно пишет:

```json
"reused_controls": {"U005": 2}
```

Это не ошибка само по себе, но это часть интерпретации uncertainty и generalization.

### Balance проверяется после matching, а не предполагается

Для каждого audited feature считается standardized mean difference:

```text
SMD = (mean_treated - mean_control) / pooled_standard_deviation
```

До matching:

```text
friction_score SMD = 1.8496
baseline_risk_score SMD = 2.6332
```

После primary matching:

```text
friction_score SMD = 1.2437
baseline_risk_score SMD = 3.5691
```

То есть friction balance улучшился, capacity стал идеально сбалансированным, но
baseline risk и pre-activation balance остались плохими или стали хуже. Хороший artifact
не прячет это за одним ATT.

## Соберите это

Артефакты урока:

```text
outputs/matching_spec.json
outputs/matching_pipeline.py
outputs/matching_report.json
```

### Шаг 1: соберите target-population cohort

Pipeline читает те же таблицы causal phase:

```text
../data/tiny/users.csv
../data/tiny/pre_treatment_behavior.csv
../data/tiny/onboarding_assistance.csv
../data/tiny/outcomes.csv
```

Затем применяет criteria из `target_trial_spec.json`:

```json
[
  {"field": "is_test_user", "operator": "==", "value": false},
  {"field": "eligible_for_program", "operator": "==", "value": true},
  {"field": "friction_score", "operator": ">=", "value": 50}
]
```

В target cohort получается:

```text
cohort_n = 10
treated_n = 6
comparator_n = 4
naive_risk_difference = -0.08333333333333337
```

### Шаг 2: стандартизируйте distance features

Для `friction_score` и `specialist_capacity` pipeline считает mean и population
standard deviation по всей target population:

```text
z = (x - mean) / std
```

Manual distance между treated user `i` и control user `j`:

```text
sqrt(sum((z_i - z_j)^2))
```

Затем artifact сверяет ручной matrix со `scipy.spatial.distance.cdist`. Это не делает
matching «библиотечным черным ящиком»: SciPy здесь только независимый контроль
арифметики.

### Шаг 3: выберите nearest neighbor внутри caliper

Primary matching pairs:

| Treated | Control | Distance | Pair effect |
|---|---|---:|---:|
| U003 | U005 | 1.091349 | -1 |
| U004 | U011 | 0.218270 | 0 |
| U006 | U007 | 0.327405 | 0 |
| U010 | U005 | 1.309619 | 0 |

Unmatched treated users:

```text
U001
U002
```

Их nearest controls дальше caliper. Это common-support warning, а не повод silently
удалить строчки без объяснения.

### Шаг 4: посчитайте matched ATT

Для каждой пары:

```text
pair_effect = treated_outcome - matched_control_outcome
```

В tiny data:

```text
matched_treated_risk = 0.5
matched_control_risk = 0.75
matched_att = -0.25
```

Сравните с предыдущими числами:

```text
naive risk difference = -0.08333333333333337
g-computation ATE = -0.39978100191623295
matched ATT subset = -0.25
```

Эти числа не обязаны совпадать: у них разные estimator assumptions и, в случае
matching, другая retained population.

## Используйте это

Запуск из корня репозитория:

```bash
python phases/13-causal-analysis/06-matching/outputs/matching_pipeline.py \
  --data-dir phases/13-causal-analysis/data/tiny \
  --target-trial phases/13-causal-analysis/01-causal-question-and-estimand/outputs/target_trial_spec.json \
  --estimand phases/13-causal-analysis/01-causal-question-and-estimand/outputs/estimand.json \
  --adjustment-gate phases/13-causal-analysis/04-colliders/outputs/bad_control_selection_audit.json \
  --matching-spec phases/13-causal-analysis/06-matching/outputs/matching_spec.json \
  --output phases/13-causal-analysis/06-matching/outputs/matching_report.json
```

Короткий пример:

```bash
python phases/13-causal-analysis/06-matching/code/main.py
```

Он печатает:

```json
{
  "matching_valid": true,
  "cohort_n": 10,
  "matched_treated_n": 4,
  "unmatched_treated_n": 2,
  "matched_att": -0.25,
  "max_abs_smd_after": 3.569124,
  "effect_claim_allowed": false
}
```

`matching_valid=true` означает: artifact корректно выполнил заявленный pipeline и не
нашел blocking errors. Это не означает «causal effect proven».

## Сломайте это

### Bad control в distance

Если добавить в `distance_features`:

```text
onboarding_completed_48h
```

report становится invalid: это mediator для total-effect question.

### Complete-case filter

Если добавить filter:

```text
telemetry_complete_30d
```

report становится invalid: это post-treatment selection variable. Даже если сейчас все
tiny rows complete, сама policy опасна и должна быть заблокирована до расчета.

### Matching без caliper

Candidate:

```text
forced_no_caliper_all_treated_match
```

отклоняется как `invalid_common_support_policy`, потому что он заставляет матчиться даже
high-risk treated users без похожих controls.

### Full ATT без replacement

В tiny data:

```text
treated = 6
controls = 4
```

Ratio-1 matching без replacement и без unmatched treated не может покрыть всех treated.
Artifact фиксирует это как `invalid_insufficient_controls_for_full_att`.

## Проверьте это

Урок содержит behavioral tests:

```bash
python -m unittest phases/13-causal-analysis/06-matching/tests/test_main.py
```

Тесты проверяют:

- exact tiny numbers для matched ATT, matched risks и unmatched users;
- ручную distance matrix против `scipy.spatial.distance.cdist`;
- nearest-neighbor pairs, caliper и replacement reuse;
- common-support warning для `U001` и `U002`;
- balance table и love plot data;
- изменение retained population;
- bad-control и complete-case policies;
- declared/calculated candidate statuses;
- duplicate source grain до join;
- treatment timing outside grace period;
- nonzero CLI exit code при invalid claim policy.

## Поставьте результат

Именованный артефакт:

```text
matching-balance-auditor
```

Файлы:

```text
outputs/matching_spec.json
outputs/matching_pipeline.py
outputs/matching_report.json
outputs/artifact.json
```

Artifact можно передать в следующие уроки как:

- matched-pair table для сравнения с IPW/AIPW;
- common-support audit для positivity diagnostics;
- balance table и love plot data для stakeholder-friendly визуализации;
- policy gate, который не дает случайно использовать mediator, selection variable или
  outcome leakage.

Важно: report сохраняет `allowed_effect_claim=false`. Matching estimate — это
ограниченный estimate для matched subset при observed-balance diagnostics, а не финальное
доказательство causal effect.

## Упражнения

1. Уменьшите caliper до `1.0`. Сколько treated users останется и как изменится matched
   ATT?
2. Отключите replacement. Какие controls используются и почему full ATT уже невозможно
   честно сохранить?
3. Добавьте `baseline_risk_score` в distance features. Улучшится ли balance по
   `activation_14d_pre`?
4. Постройте simple love plot из `love_plot_data`: какие features всё ещё выше
   threshold `0.25`?
5. Объясните заказчику, почему unmatched high-risk treated users важнее, чем само число
   `-0.25`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Matching | «Делает observational data похожими на A/B-тест» | Строит сравнимые пары/наборы по observed covariates при stated design |
| Common support | «Необязательная диагностическая формальность» | Зона covariate space, где есть и treated, и comparator units |
| Caliper | «Косметический параметр качества» | Максимально допустимая distance; защищает от forced bad matches |
| Replacement | «Ошибка, потому что control повторяется» | Политика reuse controls; снижает distance, но меняет effective control diversity |
| SMD | «p-value для balance» | Масштабированная разница средних, не зависящая от sample-size test logic |
| Love plot | «Красивая картинка» | Диагностическая таблица/граф SMD до и после adjustment |
| Matched ATT | «То же самое, что ATE» | Effect estimate для фактически treated units, которые попали в matched support |

## Дополнительное чтение

- [Hernán and Robins: Causal Inference: What If](https://miguelhernan.org/whatifbook) — главы про exchangeability, positivity и почему сравнение должно опираться на design assumptions.
- [Stuart: Matching Methods for Causal Inference](https://doi.org/10.1214/09-STS313) — обзор matching design, balance diagnostics и ограничений метода.
- [SciPy `cdist`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.distance.cdist.html) — официальный API для независимой проверки distance matrix.
- [DoWhy: Estimating Causal Effects](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html) — где matching находится в общем workflow `model -> identify -> estimate -> refute`.
