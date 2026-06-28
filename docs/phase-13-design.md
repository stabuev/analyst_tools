# Проект фазы 13: Причинный анализ

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую причинную задачу, модель данных, роли инструментов и контракт итогового
`causal-study-package`.

## Результат фазы

Студент превращает продуктовый вопрос «сработало ли вмешательство?» в воспроизводимое
наблюдательное причинное исследование. Он сначала определяет treatment, contrast,
population, time zero, outcome window и estimand, затем рисует causal DAG и объясняет,
почему эффект идентифицируем при конкретных assumptions. Только после этого выбирает
estimator, проверяет overlap и balance, проводит falsification и sensitivity checks и
ограничивает causal claim тем, что действительно поддерживает дизайн.

Фаза учит держать раздельно четыре слоя:

1. **Вопрос:** какой counterfactual contrast нужен бизнесу и для какой популяции.
2. **Идентификация:** какие assumptions связывают наблюдаемые данные с estimand.
3. **Оценка:** каким статистическим estimator вычисляется identified expression.
4. **Проверка:** какие diagnostics, placebo, negative controls и sensitivity analyses
   могут опровергнуть или ослабить вывод.

Фаза состоит из четырех последовательных блоков:

1. `13/01`-`13/04`: causal question, target trial-style spec, DAG, backdoor paths,
   confounders, colliders, mediators и selection bias.
2. `13/05`-`13/07`: regression adjustment/g-formula, matching, propensity weighting и
   doubly robust estimation.
3. `13/08`-`13/09`: Difference-in-Differences, RDD и instrumental variables как
   research designs с локальными estimands.
4. `13/10`-`13/11`: falsification, sensitivity, DoWhy automation audit и итоговый
   `causal-study-package`.

Суммарная длительность - 930 минут, или 15,5 часа.

## Границы содержания

- **Не повтор прикладной статистики.** Фаза переиспользует estimators, intervals,
  bootstrap, regression diagnostics и robust covariance из фазы 09. Здесь главный
  вопрос не «как посчитать coefficient», а «какой causal estimand этот расчет
  оценивает и при каких assumptions».
- **Не повтор A/B-тестов.** Фаза 10 учит randomized assignment, SRM, MDE, CUPED,
  multiple testing и decision protocol. Фаза 13 начинается там, где treatment уже
  выдавался неслучайно, эксперимент невозможен либо возник natural experiment.
- **Не автоматическое открытие причинного графа.** DAG строится из domain knowledge,
  временного порядка и проверяемых assumptions. Causal discovery может предложить
  гипотезы о структуре, но не заменяет содержательное обоснование стрелок и не входит в
  обязательную фазу.
- **Не каталог всех causal estimators.** Фаза покрывает outcome regression,
  matching, IPW/AIPW, простой и multi-period DiD и design audit для RDD/IV. Synthetic
  control, generalized synthetic control, matrix completion, mediation analysis,
  frontdoor, regression kink и panel DML остаются факультативными продолжениями.
- **Не longitudinal g-methods.** Time-varying treatment/confounding, marginal structural
  models, g-estimation и cloning/censoring/weighting требуют отдельной глубины. Здесь
  treatment фиксируется относительно явного time zero, а follow-up window ограничен.
- **Не heterogeneity/policy-learning курс.** ATE, ATT и локальные estimands являются
  основной целью. CATE, causal forests, uplift, DML и policy learning показываются как
  граница применения EconML, а не становятся скрытым введением в ML до фазы 15.
- **Не «контроль всех колонок».** Post-treatment variables, mediators, colliders и
  descendants of selection нельзя добавлять в model только потому, что они доступны.
  Adjustment set выводится из causal assumptions, а не из feature importance или
  p-value.
- **Не обещание, что diagnostics доказывают assumptions.** Balance after matching,
  pre-trends, placebo и refutation tests могут обнаружить несовместимость с дизайном,
  но успешная проверка не доказывает отсутствие unobserved confounding, exclusion
  violation или interference.
- **Не forecasting и causal impact по одному ряду.** DiD использует comparison groups и
  parallel-trends design. Seasonality, forecasting, rolling backtesting и prediction
  intervals остаются фазе 14.
- **Не polished stakeholder delivery.** `13/11` собирает проверяемый research package и
  ограниченный evidence statement. Memo, презентация, dashboard, PDF/HTML/DOCX и
  интерактивная поставка остаются фазе 17.

## Роли инструментов

Новые зависимости на этапе проектирования не добавляются. NetworkX и DoWhy должны
появиться в locked environment только вместе с первым уроком, который реально их
запускает, после проверки совместимости с текущими Python, NumPy, pandas и statsmodels.
EconML не становится обязательной зависимостью по умолчанию: сначала должна быть
отдельно обоснована задача heterogeneous treatment effects, а не просто желание
использовать более сложную библиотеку.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| Python / NumPy | Ручные counterfactual tables, standardization, matching distances, IPW/AIPW formulas, simulations и deterministic fixtures | Новый обзор NumPy и сложные semiparametric proofs |
| pandas | Сбор analysis cohort, time-zero filters, matching/weighting tables, balance diagnostics и panel preparation | Новый обзор DataFrame API и distributed processing |
| DuckDB | Независимые проверки grain, treatment timing, cohort eligibility, panel completeness и reconciliation | Warehouse orchestration, dbt graph и production BI |
| statsmodels | Outcome/propensity models, robust covariance, `TreatmentEffect` RA/IPW/AIPW и regression-style DiD | Автоматическая идентификация, causal discovery и все econometric designs |
| SciPy | Distances, distributions, standardized differences, tests и небольшие sensitivity calculations | Каталог всех statistical tests |
| NetworkX | DAG structure, cycle/temporal-order checks, d-separation и minimal separator experiments | Обучение causal graph из observational data |
| DoWhy | Явный workflow `model -> identify -> estimate -> refute` и сверка автоматизации с прозрачным расчетом | Автоматическое создание правдоподобных assumptions и гарантия causal validity |
| EconML | Ориентир для CATE/DML/DRLearner и граница между average effect и heterogeneity | Обязательный ML-стек, causal forests, policy learning и скрытая замена фазы 15 |
| Pandera / Pydantic | Контракты causal question, estimand, DAG, adjustment set, estimator и diagnostics | Production governance platform |
| Matplotlib / Seaborn | Love plot, propensity overlap, event-study, cutoff и sensitivity figures | Новая gallery визуализаций |
| pytest | Behavioral checks для identification contract, manual estimators, diagnostics и final package | Повтор основ pytest/CI |

Проверенные на 25 июня 2026 года официальные и первичные ориентиры:

- [Hernán и Robins: Causal Inference: What If](https://miguelhernan.org/whatifbook) -
  бесплатный первичный учебник по target trial, exchangeability, positivity,
  standardization, IP weighting и ограничениям observational causal inference.
- [DoWhy documentation](https://www.pywhy.org/dowhy/main/index.html) - актуальная
  документация ветки `main` датирована 24 июня 2026 года; stable release list содержит
  `v0.14`, а библиотека явно разделяет assumptions, identification, estimation и
  refutation.
- [DoWhy: Estimating Causal Effects](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html)
  - workflow `model`, `identify`, `estimate`, `refute`, backdoor/IV identification и
  estimators matching, propensity, regression и RDD.
- [statsmodels: Treatment Effects](https://www.statsmodels.org/stable/treatment.html) -
  API 0.14.6 оценивает effects under conditional independence и предоставляет RA, IPW,
  AIPW, AIPW-WLS и IPW-RA с GMM-based inference. В этой версии outcome model класса
  `TreatmentEffect` ограничена OLS, поэтому binary outcomes требуют явной проверки
  linear-probability approximation или отдельной transparent GLM standardization.
- [NetworkX: D-Separation](https://networkx.org/documentation/stable/reference/algorithms/d_separation.html)
  - stable API 3.6.1 для `is_d_separator`, `find_minimal_d_separator` и проверки
  graphical conditional independence.
- [EconML 0.16.0 documentation](https://www.pywhy.org/EconML/index.html) - CATE, DML,
  doubly robust learners, forests, IV estimators и sensitivity API; это подтверждает,
  что библиотека решает более широкую ML-based heterogeneity-задачу и не должна
  подменять базовую идентификацию.
- [Callaway и Sant'Anna: Difference-in-Differences with Multiple Time Periods](https://arxiv.org/abs/1803.09015)
  - primary source по multi-period и staggered DiD, group-time effects, covariates,
  IPW/outcome-regression/doubly robust estimands и aggregation.
- [Baker et al.: Difference-in-Differences Designs: A Practitioner's Guide](https://arxiv.org/abs/2503.13323)
  - современная карта DiD designs, estimators, covariates, weights, multiple periods и
  staggered treatment.
- [Cinelli и Hazlett: Making Sense of Sensitivity](https://doi.org/10.1111/rssb.12348)
  - primary source по omitted-variable-bias sensitivity через partial R-squared и
  robustness values.

При разработке конкретного урока API и версии необходимо сверять с фактически
зафиксированным `uv.lock`, а не только с online-документацией.

## Единая причинная задача и данные

Фаза использует ту же вымышленную продуктовую вселенную. Рабочий вопрос интеграционного
проекта:

> Помогает ли assisted onboarding повысить `activation_14d` и
> `paid_subscription_30d` у пользователей с высоким риском незавершенного onboarding,
> если программа выдавалась неслучайно и ее доступность зависела от risk score,
> региона, платформы и свободной capacity специалистов?

Команда не может интерпретировать простую разницу treated/control:

- assisted onboarding чаще получали пользователи с высоким friction risk;
- регионы подключались поэтапно и имели разные исходные тренды;
- eligibility использовала порог risk score, но участие после offer было неполным;
- при дефиците slots часть eligible users получала randomized encouragement;
- telemetry completeness и открытие support chat зависели и от проблем пользователя, и
  от treatment;
- latent motivation влияет и на принятие помощи, и на outcome, но не наблюдается напрямую.

Такой дизайн позволяет на одной предметной задаче показать несколько разных estimands и
identification strategies, не выдавая их за взаимозаменяемые.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `users` | один eligible user | `user_id` |
| `pre_treatment_behavior` | один user-level baseline до time zero | `user_id` |
| `onboarding_assistance` | один program record пользователя | `program_id, user_id` |
| `outcomes` | один user-level набор outcome windows | `user_id` |
| `encouragement_assignments` | одно назначение encouragement eligible user | `encouragement_id` |
| `rollout_calendar` | один rollout wave региона | `region_id, rollout_version` |
| `region_week_panel` | один регион и одна календарная неделя | `region_id, week_start` |
| `causal_scenarios` | один machine-readable causal design | `scenario_id` |

Ключевые поля `onboarding_assistance`:

| Поле | Смысл |
|---|---|
| `user_id` | unit of analysis |
| `time_zero` | момент, относительно которого определяются treatment и follow-up |
| `friction_score` | pre-treatment score, используемый в eligibility |
| `eligibility_cutoff` | порог для offer и RDD design |
| `offered_assistance` | был ли пользователь приглашен |
| `received_assistance` | фактический binary treatment |
| `offered_at` | время offer |
| `started_at` | время фактического начала помощи |
| `region_id` | регион rollout/capacity |
| `specialist_capacity` | доступная pre-treatment capacity |
| `assignment_reason` | score threshold, regional rollout, manual override или lottery |

Ключевые baseline covariates:

```text
platform
device_tier
acquisition_channel
region_id
language
network_quality
app_crashes_before_time_zero
onboarding_steps_before_time_zero
sessions_before_time_zero
friction_score
specialist_capacity
signup_cohort
```

Outcomes и post-treatment variables:

```text
activation_14d
paid_subscription_30d
cancelled_subscription_30d
refund_amount_30d
support_minutes_14d
onboarding_completed_48h
opened_support_chat_after_offer
telemetry_complete_30d
```

`onboarding_completed_48h` является mediator для total-effect question.
`opened_support_chat_after_offer` может быть collider между treatment и frustration.
`telemetry_complete_30d` создает selection bias, если analysis silently оставляет только
полные outcomes.

Профили данных:

- `tiny`: десятки users, два региона, ручные expected values для naive difference,
  standardization, exact matching, stabilized IPW, AIPW, 2x2 DiD и Wald ratio;
- `sample`: детерминированная локальная генерация тысяч users и нескольких rollout waves
  для balance, overlap, multi-period DiD, cutoff и sensitivity;
- дефектные fixtures: минимальные мутации valid baseline для одного failure mode;
- скрытый generator truth: true potential outcomes и latent motivation доступны только
  тестам генератора, но не analysis code студента.

Заложенные свойства и failure modes:

- confounding by indication: более сложных пользователей чаще лечат;
- Simpson-like reversal между aggregate и adjusted effect;
- post-treatment leakage через onboarding completion и support chat;
- collider bias после фильтра `opened_support_chat_after_offer = true`;
- selection bias после complete-case filter по telemetry;
- positivity violation: в части region/risk cells нет untreated или treated users;
- extreme propensity weights и маленький effective sample size;
- matching улучшает balance, но меняет target population и estimand;
- outcome model без interaction/non-linearity дает regression misspecification;
- propensity model без нужной нелинейности дает плохой balance;
- AIPW сохраняет разумный результат при одной корректной nuisance model, но ломается,
  когда обе модели misspecified или overlap отсутствует;
- регион с pre-existing trend нарушает naive parallel trends;
- staggered rollout делает один TWFE coefficient трудно интерпретируемой смесью effects;
- risk score имеет heaping/manipulation около cutoff;
- encouragement слабо влияет на actual treatment в одном сегменте;
- exclusion restriction нарушается, если encouragement само содержит полезный tutorial;
- IV оценивает LATE для compliers, а не population ATE;
- unobserved motivation достаточно сильна, чтобы sensitivity interval пересекал ноль;
- placebo outcome или pre-treatment outcome реагирует на «treatment», сигнализируя о
  проблеме дизайна.

## Контракт causal study

Каждый урок работает через machine-readable causal spec:

```text
question_id
business_decision
target_population
eligibility
unit_of_analysis
time_zero
treatment
treatment_versions
contrast
outcomes
followup_windows
estimand
effect_scale
causal_graph
identification_strategy
adjustment_set
measured_confounders
unmeasured_confounders
forbidden_controls
consistency_assumption
exchangeability_assumption
positivity_assumption
interference_assumption
missingness_and_selection
estimator
propensity_model
outcome_model
overlap_policy
balance_thresholds
weight_policy
quasi_experiment_assumptions
falsification_checks
sensitivity_parameters
claim_policy
known_limitations
```

Spec не является разрешением на causal wording. Он должен показывать цепочку:

```text
question -> estimand -> assumptions -> identification -> estimator -> diagnostics -> claim
```

Если effect не identified, overlap отсутствует, treatment определен после outcome,
adjustment set содержит bad control или design assumptions явно нарушены, package обязан
выпустить `not_identified`, `design_invalid` или `inconclusive`, а не число с осторожной
сноской.

## Контракт отдельных методов

### Regression adjustment / g-formula

- prediction строится отдельно под `T=1` и `T=0` для одной и той же target population;
- ATE/ATT различаются aggregation population, а не названием колонки;
- standardization сверяется с ручным tiny calculation;
- nonlinearities и treatment interactions являются model assumptions;
- extrapolation за common support фиксируется в diagnostics;
- robust standard errors не исправляют confounding или misspecification.

### Matching

- matching использует только pre-treatment covariates;
- distance/propensity, caliper, replacement, ratio и tie policy фиксируются заранее;
- до и после matching публикуются SMD, variance ratio и overlap;
- unmatched units не исчезают молча: отчет показывает, какая population осталась;
- p-values balance tests не заменяют substantive balance diagnostics.

### IPW / AIPW

- propensity scores ограничены treatment assignment model, а не outcome prediction;
- публикуются raw/stabilized/truncated weights, tails и effective sample size;
- positivity failures не лечатся косметическим clipping без изменения target
  population или estimand;
- AIPW сравнивается с RA и IPW на одном estimand;
- doubly robust не означает «неуязвимый»: требуется корректность хотя бы одной nuisance
  model и достаточный overlap.

### Difference-in-Differences

- сначала строится прозрачный 2x2 calculation;
- treatment timing и comparison group фиксируются до regression;
- pre-trends plot является diagnostic, но не доказательством parallel trends;
- anticipatory effects, composition changes и concurrent shocks проверяются отдельно;
- multi-period/staggered design публикует group-time effects или явно объясняет, почему
  один TWFE coefficient допустим;
- standard errors учитывают уровень treatment assignment/clustering.

### RDD / IV

- RDD требует явного running variable, cutoff, treatment rule, bandwidth и local
  population;
- проверяются density/heaping/manipulation, continuity pre-treatment covariates и
  sensitivity к bandwidth/specification;
- IV требует relevance, exclusion, independence и monotonicity assumptions;
- weak first stage блокирует strong causal claim;
- LATE/complier effect не переименовывается в ATE;
- fuzzy RDD рассматривается как IV-like local design, а не как глобальный threshold
  effect.

## Интеграционный мини-проект

`13/11` собирает поставку:

```text
causal-study-package/
├── question/
│   ├── causal-question.json
│   ├── target-trial-spec.json
│   └── estimand.json
├── graph/
│   ├── causal-dag.json
│   ├── identification-report.json
│   ├── adjustment-set.json
│   └── forbidden-controls.json
├── data/
│   ├── source-contract.json
│   ├── cohort-audit.json
│   └── analysis-cohort.csv
├── adjustment/
│   ├── naive-and-regression-adjusted.csv
│   ├── matching-estimates.csv
│   ├── balance-table.csv
│   ├── propensity-overlap.csv
│   ├── weight-diagnostics.json
│   └── ipw-aipw-estimates.csv
├── quasi-experiments/
│   ├── did-estimates.csv
│   ├── event-study.csv
│   ├── did-placebos.json
│   └── rdd-iv-design-audit.json
├── robustness/
│   ├── placebo-tests.json
│   ├── negative-controls.json
│   ├── estimator-comparison.csv
│   └── sensitivity-analysis.json
├── automation/
│   ├── dowhy-workflow.json
│   ├── transparent-vs-library.csv
│   └── econml-scope-audit.json
├── figures/
│   ├── dag.png
│   ├── balance-love-plot.png
│   ├── propensity-overlap.png
│   ├── event-study.png
│   └── sensitivity-plot.png
├── report.md
├── claim.json
└── manifest.json
```

Пакет обязан:

- зафиксировать treatment, contrast, time zero, target population, outcome windows и
  estimand до расчета;
- содержать DAG без циклов, temporal-order violations и неописанных ключевых стрелок;
- перечислить identification assumptions и adjustment set;
- запретить colliders, mediators и post-treatment descendants в total-effect adjustment;
- проверить cohort grain, treatment/outcome timing, missingness и selection;
- показать naive estimate как baseline, но не как causal answer;
- сравнить RA, matching, IPW и AIPW на одном estimand;
- публиковать balance, overlap, extreme weights и effective sample size;
- явно фиксировать target population после matching/trimming;
- для DiD показать group/time structure, pre-trends, placebos и ограничение staggered
  adoption;
- для RDD/IV публиковать local estimand и assumption audit даже если design отвергнут;
- проводить минимум один placebo treatment/outcome, один negative control и один
  unobserved-confounding sensitivity analysis;
- воспроизводить DoWhy `model -> identify -> estimate -> refute` workflow и сверять
  library estimate с прозрачной реализацией;
- объяснять, почему EconML нужен или не нужен для текущего вопроса, не запускать CATE
  только ради сложности;
- выпускать claim из ограниченного набора:
  `identified_under_stated_assumptions`, `assumption_sensitive`, `not_identified`,
  `design_invalid`, `inconclusive`;
- связывать каждый causal claim с estimand id, assumption ids, estimate id,
  diagnostics и sensitivity result;
- выпускать SHA-256 manifest всех переданных файлов и generation parameters.

## Проверяемость

- Tiny-profile содержит ручные expected values для potential-outcome table, naive
  difference, standardization, exact matching, SMD, stabilized weights, AIPW, 2x2 DiD
  и Wald ratio.
- Causal question tests проверяют treatment/contrast, time zero, outcome order,
  population, estimand и consistency между target trial и data contract.
- DAG tests проверяют acyclicity, known nodes, temporal order, d-separation и изменение
  open paths после conditioning on confounder/collider.
- Adjustment-set tests блокируют mediator, collider, descendant of treatment и
  selection variable; missing unmeasured confounder должен оставаться limitation.
- Regression-adjustment tests сверяют manual g-computation со statsmodels result и
  ловят wrong aggregation population, interaction omission и extrapolation.
- Matching tests проверяют deterministic tie policy, caliper, replacement, matched
  population, SMD improvement и честный отчет о discarded units.
- Weighting tests проверяют propensity bounds, stabilized weights, truncation policy,
  effective sample size, RA/IPW/AIPW consistency и double-misspecification failure.
- DiD tests сверяют ручную 2x2 difference, event-time construction, pre-trend/placebo
  flags, treatment timing и запрет naive TWFE claim при staggered heterogeneous effects.
- RDD/IV tests проверяют cutoff contract, bandwidth sensitivity, manipulation/heaping,
  first stage, exclusion warning, monotonicity и LATE wording.
- Sensitivity tests проверяют direction and scale perturbation, placebo/negative-control
  failures и порог unobserved confounding, при котором claim меняется.
- DoWhy integration test проверяет совпадение estimand/adjustment set и tolerance
  library estimate с transparent implementation; refuter не считается доказательством.
- Final package test проверяет структуру, manifest, checksums, claim-to-evidence links,
  отсутствие unsupported causal wording и consistency между question, estimand,
  identification, estimates и limitations.
