# RDD и instrumental variables: дизайн до оценки

> Quasi-experiment начинается не с регрессии, а с вопроса: почему именно здесь
> counterfactual стал правдоподобнее, чем в обычном observational comparison?

**Тип:** Case  
**Треки:** Decision, Product  
**Пререквизиты:** 13/08 — Difference-in-Differences  
**Время:** ~75 минут  
**Результат:** проверяет применимость RDD и IV, формулирует локальный estimand,
continuity/relevance/exclusion/monotonicity assumptions и обнаруживает manipulation at
cutoff, weak instrument и неверное обобщение LATE на ATE.

## Цели обучения

- Отличать quasi-experimental design от «ещё одной регрессии с красивым названием».
- Формулировать local estimand для regression discontinuity design.
- Проверять running variable, cutoff, bandwidth, manipulation и continuity diagnostics.
- Различать sharp RDD и fuzzy RDD.
- Считать first stage, reduced form и Wald diagnostic в fuzzy RDD.
- Формулировать IV assumptions: relevance, independence, exclusion, monotonicity.
- Считать IV first stage, reduced form и Wald LATE.
- Не превращать local RDD effect или IV LATE в population ATE.

## Проблема

В данных фазы есть два квази-экспериментальных намёка:

```text
onboarding_assistance.csv
encouragement_assignments.csv
```

Первый намёк — cutoff:

```text
friction_score >= 60  ->  user is eligible for assistance offer
```

Наивная мысль:

```text
сравним пользователей с friction_score 61 и 59, почти одинаковые же
```

Это похоже на RDD, но только если running variable нельзя манипулировать, около cutoff
достаточно наблюдений, baseline-поведение меняется непрерывно, а эффект интерпретируется
локально около `60`, а не для всех пользователей.

Второй намёк — encouragement:

```text
capacity_lottery_v1 encouraged some users before time zero
```

Наивная мысль:

```text
encouragement случайный, значит можно оценить эффект assistance
```

Это похоже на IV, но только если encouragement действительно влияет на treatment take-up
и не влияет на activation напрямую, кроме как через получение assistance. Даже тогда
результат — LATE для compliers, а не ATE для всей population.

## Концепция

### RDD: локальный counterfactual у cutoff

Regression discontinuity design использует правило:

```text
running_variable >= cutoff
```

Идея: пользователи чуть ниже и чуть выше cutoff похожи, кроме резкого изменения
вероятности treatment. В уроке:

```text
running variable = friction_score
cutoff           = 60
bandwidth        = 8
treatment        = offered_assistance
outcome          = activation_14d
```

Локальное окно:

```text
52 <= friction_score <= 68
```

Важно: RDD не говорит «эффект для всех пользователей». Он говорит:

```text
local effect near friction_score = 60
```

Если бизнес просит вывод про всех пользователей с friction score от 40 до 90, RDD сам по
себе этого не даёт.

### Sharp и fuzzy RDD

Sharp RDD требует, чтобы treatment полностью определялся cutoff:

```text
score >= 60 -> treatment = 1
score < 60  -> treatment = 0
```

В tiny data есть пользователь:

```text
U006: friction_score = 58, offered_assistance = true, assignment_reason = manual_override
```

Значит sharp RDD неверен. Правильнее обозначить дизайн как fuzzy RDD: cutoff меняет
вероятность treatment, но не назначает его идеально.

Artifact считает локальный first stage:

```text
P(offer | score >= 60) - P(offer | score < 60)
= 1.000 - 0.333
= 0.667
```

Reduced form по outcome:

```text
P(activation | score >= 60) - P(activation | score < 60)
= 0.333 - 1.000
= -0.667
```

Wald diagnostic:

```text
-0.667 / 0.667 = -1.000
```

Это специально называется diagnostic: в игрушечном окне всего 6 строк, поэтому число
помогает проверить механику, но не является стабильной бизнес-оценкой.

### Manipulation и continuity

RDD ломается, если люди или система могут подвинуть running variable:

```text
score 59 -> score 60
```

Тогда пользователи справа и слева от cutoff перестают быть почти-случайно разделёнными.
В уроке artifact делает простой density screen: считает наблюдения слева и справа внутри
bandwidth. Это не полноценный McCrary test, но хороший первый guardrail.

Второй guardrail — continuity по pre-treatment covariates. В tiny data проверяется:

```text
specialist_capacity
```

Слева и справа от cutoff среднее совпадает:

```text
left_mean  = 1.333
right_mean = 1.333
difference = 0.000
```

Это не доказывает continuity assumption, но может поймать очевидный скачок.

### IV: instrument двигает treatment, но не outcome напрямую

Instrumental variables design использует переменную `Z`, которая меняет treatment `D`, а
outcome `Y` меняет только через `D`.

В уроке:

```text
Z = encouraged
D = received_assistance
Y = activation_14d
```

Assumptions:

- **Relevance:** encouragement меняет вероятность получить assistance.
- **Independence / as-if random:** encouragement не связан с потенциальными outcomes.
- **Exclusion restriction:** encouragement влияет на activation только через assistance.
- **Monotonicity:** encouragement никого не делает менее склонным получить assistance.

Artifact считает:

```text
first stage = P(D=1 | Z=1) - P(D=1 | Z=0)
            = 0.800 - 0.400
            = 0.400

reduced form = P(Y=1 | Z=1) - P(Y=1 | Z=0)
             = 0.800 - 0.600
             = 0.200

Wald LATE = reduced form / first stage
          = 0.200 / 0.400
          = 0.500
```

Это LATE для compliers: пользователей, чьё получение assistance изменилось из-за
encouragement. Это не ATE для всех eligible users.

## Соберите это

Файлы урока:

```text
outputs/quasi_experiment_spec.json
outputs/quasi_experiment_design_auditor.py
outputs/quasi_experiment_report.json
```

### Шаг 1: проверьте источники и scenario registry

Artifact проверяет declared grain:

```text
pre_treatment_behavior: user_id
onboarding_assistance: program_id, user_id
outcomes: user_id
encouragement_assignments: encouragement_id
causal_scenarios: scenario_id
```

Затем сверяет spec с `causal_scenarios.csv`:

| Scenario | Design | Estimand |
|---|---|---|
| score_rdd | regression_discontinuity | local_ATE |
| capacity_iv | instrumental_variables | LATE |

Если spec просит `missing_score_rdd`, report становится invalid до оценки.

### Шаг 2: соберите RDD local window

Primary RDD:

```text
cutoff = 60
bandwidth = 8
```

Локальная таблица:

| user_id | friction_score | side | offered | activation | reason |
|---|---:|---|---|---|---|
| U012 | 52 | left | false | true | below_cutoff |
| U007 | 55 | left | false | true | below_cutoff |
| U006 | 58 | left | true | true | manual_override |
| U005 | 61 | right | true | true | score_threshold_capacity_full |
| U011 | 64 | right | true | false | score_threshold_capacity_full |
| U004 | 66 | right | true | false | score_threshold |

Главная находка:

```text
U006 violates sharp assignment
```

Значит candidate `sharp_score_cutoff_offer` получает статус:

```text
invalid_requires_fuzzy_rdd
```

### Шаг 3: проверьте manipulation и continuity

Density screen:

```text
left rows  = 3
right rows = 3
density_ratio = 1.0
```

Continuity screen:

```text
specialist_capacity difference = 0.0
```

Если несколько пользователей внезапно «переедут» с 55-58 на 61, density ratio станет
подозрительным. Если справа от cutoff резко вырастет baseline capacity, local comparison
перестанет быть credible.

### Шаг 4: соберите IV first stage и LATE contract

Instrument groups:

| Group | Rows | Treatment rate | Outcome rate |
|---|---:|---:|---:|
| encouraged | 5 | 0.800 | 0.800 |
| not encouraged | 5 | 0.400 | 0.600 |

Artifact фиксирует:

```text
first_stage = 0.4
wald_late = 0.5
```

Порог в spec:

```text
minimum_first_stage = 0.3
```

Если поднять порог до `0.5`, check `iv_first_stage_is_relevant_enough_for_tiny_design`
блокирует claim policy.

### Шаг 5: проверьте candidate policy

Artifact не просто считает числа, а маркирует design candidates:

| Candidate | Status |
|---|---|
| primary_fuzzy_score_rdd | estimable_local_with_assumptions |
| sharp_score_cutoff_offer | invalid_requires_fuzzy_rdd |
| wide_bandwidth_ignores_locality | invalid_not_local |
| capacity_encouragement_late | estimable_late_with_assumptions |
| encouragement_claims_ate | invalid_late_generalized_to_ate |
| weak_encouragement_variant | invalid_weak_instrument |

Это защищает от типовой ошибки: «раз есть инструмент, пишем ATE».

## Используйте это

Запуск artifact из корня репозитория:

```bash
python phases/13-causal-analysis/09-quasi-experiments/outputs/quasi_experiment_design_auditor.py
```

Он обновляет:

```text
phases/13-causal-analysis/09-quasi-experiments/outputs/quasi_experiment_report.json
```

Короткий пример:

```bash
python phases/13-causal-analysis/09-quasi-experiments/code/main.py
```

Ожидаемый summary:

```json
{
  "quasi_design_valid": true,
  "rdd_design_type": "fuzzy_rdd",
  "rdd_local_rows_n": 6,
  "rdd_first_stage": 0.666667,
  "rdd_wald_local_effect_diagnostic": -1.0,
  "iv_first_stage": 0.4,
  "iv_wald_late": 0.5,
  "allowed_local_claim": true
}
```

Для CI:

```bash
python phases/13-causal-analysis/09-quasi-experiments/outputs/quasi_experiment_design_auditor.py \
  --fail-on-invalid
```

Warnings в committed report:

```text
rdd_tiny_wald_estimate_is_diagnostic_only
iv_exclusion_and_monotonicity_cannot_be_proven_from_observed_data
```

Они не ломают report, но обязаны попасть в интерпретацию.

## Сломайте это

### Manipulation at cutoff

Поменяйте `friction_score` пользователей `U007` и `U012` на `61`. Теперь справа от cutoff
слишком много наблюдений:

```text
rdd_no_visible_running_variable_bunching_inside_bandwidth = false
```

### Too narrow bandwidth

Поставьте:

```json
"bandwidth": 1
```

Локальное окно почти пустое, и check
`rdd_has_observations_on_both_sides_inside_bandwidth` блокирует design.

### Covariate jump

Поднимите `specialist_capacity` только справа от cutoff. Check:

```text
rdd_observed_covariates_are_continuous_at_cutoff
```

становится blocking error.

### Weak instrument

Поставьте:

```json
"minimum_first_stage": 0.5
```

При observed first stage `0.4` artifact блокирует IV claim.

### LATE as ATE

Поменяйте declared IV estimand на `ATE`. Artifact отклонит формулировку:

```text
iv_estimand_contract_is_late_not_ate = false
claim_policy_allows_only_local_rdd_and_late_wording = false
```

### Duplicate source grain

Продублируйте строку в `encouragement_assignments.csv`. Это ломает source grain и
останавливает audit до доверия к IV rows.

## Проверьте это

Поведенческие тесты:

```bash
python -m unittest phases/13-causal-analysis/09-quasi-experiments/tests/test_main.py
```

Покрытие:

- expected tiny RDD/IV numbers;
- runnable `code/main.py`;
- explicit fuzzy RDD violation;
- local window, density screen и continuity screen;
- IV first stage, reduced form и Wald LATE;
- candidate design status policy;
- manipulation at cutoff;
- too narrow bandwidth;
- covariate jump near cutoff;
- weak instrument;
- LATE-to-ATE overclaim;
- duplicate source grain;
- scenario registry alignment;
- CLI `--fail-on-invalid`;
- committed report reproducibility.

## Поставьте результат

Именованный artifact:

```text
quasi-experiment-design-auditor
```

Файлы:

```text
outputs/quasi_experiment_design_auditor.py
outputs/quasi_experiment_spec.json
outputs/quasi_experiment_report.json
outputs/artifact.json
```

Handoff-фраза:

```text
RDD design is fuzzy, local to friction_score cutoff 60 with bandwidth 8, and passes
basic density/continuity screens on tiny data. The local Wald RDD number is diagnostic
only because the window has 6 rows. The capacity encouragement IV has first stage 0.4
and Wald LATE 0.5, but the claim must remain LATE-for-compliers under relevance,
as-if-random assignment, exclusion and monotonicity assumptions; it is not an ATE.
```

## Упражнения

1. Сделайте RDD bandwidth равным `4`. Какие строки останутся в local window и почему
   side support станет хуже?
2. Добавьте пользователя с `friction_score = 60` и `offered_assistance = false`. Это
   sharp violation или manipulation warning?
3. Снимите `U006` manual override. Как изменится RDD first stage и candidate
   `sharp_score_cutoff_offer`?
4. Поменяйте `encouraged=false` для `U010`. Как изменится IV first stage и Wald LATE?
5. Напишите handoff в одну фразу так, чтобы не назвать IV LATE population ATE.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| RDD | «Сравнить всех выше и ниже threshold» | Локальный дизайн около cutoff при continuity и отсутствии manipulation |
| Running variable | «Любой score в данных» | Переменная, которая определяет или резко меняет вероятность treatment у cutoff |
| Bandwidth | «Чем шире, тем больше данных и лучше» | Компромисс между локальностью и variance; слишком широкое окно меняет estimand |
| Sharp RDD | «Threshold примерно влияет на treatment» | Treatment детерминированно задается cutoff |
| Fuzzy RDD | «RDD сломан» | Cutoff меняет вероятность treatment; нужен first-stage/Wald logic |
| Instrument | «Любая случайная переменная рядом с treatment» | Переменная, которая двигает treatment и влияет на outcome только через treatment |
| First stage | «Техническая деталь IV» | Проверка relevance: насколько instrument меняет treatment |
| Exclusion restriction | «Можно проверить по данным» | Assumption, что instrument не влияет на outcome напрямую |
| Monotonicity | «Все всегда obey instrument» | Нет defiers: instrument не уменьшает treatment take-up ни для кого |
| LATE | «ATE с другим названием» | Local average treatment effect для compliers |

## Дополнительное чтение

- [Imbens and Lemieux, 2008](https://doi.org/10.1016/j.jeconom.2007.05.001) — практический обзор RDD; читать про bandwidth, графики и continuity checks.
- [Lee and Lemieux, 2010](https://doi.org/10.1257/jel.48.2.281) — подробный эконометрический обзор RDD; полезен для ограничений локальной интерпретации.
- [McCrary, 2008](https://doi.org/10.1016/j.jeconom.2007.05.005) — первичный источник density/manipulation test для running variable около cutoff.
- [Imbens and Angrist, 1994](https://www.jstor.org/stable/2951620) — первичный источник LATE и IV assumptions; читать, чтобы не обобщать complier effect на всех.
- [Stock, Wright and Yogo, 2002](https://doi.org/10.1198/073500102288618658) — обзор weak instruments; полезен после урока, чтобы понять, почему слабый first stage опасен.
