# Проект фазы 10: Эксперименты и A/B-тесты

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую экспериментальную задачу, модель данных, роли библиотек и контракт итогового
experiment decision package.

## Результат фазы

Студент превращает продуктовую гипотезу в проверяемый онлайн-эксперимент: заранее
фиксирует протокол, выбирает единицу рандомизации, проверяет качество назначения,
планирует MDE и мощность, оценивает эффект и неопределенность, защищается от SRM,
множественных проверок, peeking и post-hoc сегментов, а затем принимает решение по
объявленному правилу.

Фаза не учит искать p-value как разрешение на запуск. Она учит отделять:

- продуктовую гипотезу от статистической гипотезы;
- assignment от exposure и outcome;
- primary metric от guardrails и exploratory checks;
- planned analysis от post-hoc расследования;
- статистический сигнал от продуктового решения с рисками.

Фаза состоит из четырех последовательных блоков:

1. `10/01`-`10/03`: experiment protocol, randomization unit, assignment health, A/A и
   Sample Ratio Mismatch.
2. `10/04`-`10/07`: MDE/power, effect estimation, bootstrap для сложных метрик и CUPED.
3. `10/08`-`10/10`: multiple testing, peeking/sequential monitoring и heterogeneity.
4. `10/11`: интеграционный experiment decision package.

Суммарная длительность - 945 минут, или 15,75 часа.

## Границы содержания

- **Не повтор продуктовой аналитики.** Фаза переиспользует metric tree, tracking plan,
  guardrails, cohorts и segmentation из фазы 08, но не заново учит считать продуктовые
  метрики. Здесь главный вопрос - можно ли интерпретировать различие как эффект
  вмешательства при валидном экспериментальном дизайне.
- **Не повтор прикладной статистики.** Confidence intervals, bootstrap, regression
  diagnostics и assumptions уже систематизированы в фазе 09. Здесь эти инструменты
  применяются к randomized assignment, traffic allocation, decision rules и experiment
  failure modes.
- **Не полный causal inference курс.** Randomized experiment дает причинную
  интерпретацию только при выполненных assumptions: stable assignment, no leakage,
  no interference, корректный exposure и измеренный outcome. DAG, confounders,
  colliders, propensity, DiD, RDD и sensitivity analysis остаются фазе 13.
- **Не платформа экспериментов и feature flags.** Студент строит локальный assignment
  engine, exposure audit и protocol validator. Production rollout, SDK, флаги, realtime
  routing, alerting и доступы к платформе остаются за границей обязательной фазы.
- **Не Bayesian/bandit-оптимизация.** Фаза покрывает fixed-horizon A/B, planned
  monitoring и простые sequential checks. Thompson sampling, multi-armed bandits,
  Bayesian decision analysis и adaptive allocation не становятся пререквизитом.
- **Не time-series/long-term holdout курс.** Calendar effects, novelty risk и delayed
  outcomes фиксируются как ограничения и guardrails. Forecasting, seasonality models,
  rolling backtesting и long-term causal measurement остаются другим фазам.
- **Не polished stakeholder delivery.** `10/11` собирает проверяемый пакет решения, но
  финальная упаковка в memo, dashboard, PDF/HTML/DOCX или интерактивный продукт остается
  фазе 17.

## Роли инструментов

Новых обязательных библиотек фаза не добавляет. Она использует стек, уже введенный в
фазах 00-09.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pandas | User-level experiment tables, assignment/exposure joins, metric windows, segment tables | Новый обзор DataFrame API |
| DuckDB | Независимые SQL-проверки exposure grain, variant counts, metric reconciliation и leakage | dbt graph, warehouse orchestration и production BI |
| NumPy | Hash/bucket simulation, RNG, permutation tests, power simulation и reproducible resampling | Полный курс stochastic processes |
| SciPy | Welch/t-tests, chi-square SRM checks, bootstrap/permutation и FDR helpers | Все статистические тесты и Bayesian inference |
| statsmodels | Power/sample-size calculations, proportions, multiple-testing procedures и optional regression-style adjustment | Полная econometrics/causal suite |
| Pandera/Pydantic | Контракты experiment protocol, metric specs, decision rules и machine-readable audits | Production data quality platform и API schemas |
| Matplotlib/Seaborn | Power curves, null distributions, peeking simulation и compact diagnostic figures | Новая gallery визуализаций и dashboard layout |

Проверенные официальные и первичные ориентиры:

- [SciPy `ttest_ind`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html)
  - независимые двухвыборочные тесты, Welch mode через `equal_var=False`, alternative
  hypotheses и trimmed option.
- [SciPy `bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)
  - confidence interval для произвольной statistic, `paired`, `method`, `n_resamples` и
  воспроизводимый `rng`.
- [SciPy `false_discovery_control`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.false_discovery_control.html)
  - Benjamini-Hochberg и Benjamini-Yekutieli для FDR.
- [statsmodels `TTestIndPower`](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.html)
  - power и sample-size calculations для двух независимых выборок.
- [statsmodels `proportion_effectsize`](https://www.statsmodels.org/stable/generated/statsmodels.stats.proportion.proportion_effectsize.html)
  - effect size для power calculation по двум долям.
- [statsmodels `multipletests`](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)
  - Bonferroni, Sidak, Holm, FDR и другие корректировки множественных проверок.
- [Ensure A/B Test Quality at Scale with Automated Randomization Validation and Sample Ratio Mismatch Detection](https://arxiv.org/abs/2208.07766)
  - primary source по automated randomization validation и SRM в крупной платформе
  экспериментов.
- [Trustworthy Experimentation Under Telemetry Loss](https://arxiv.org/abs/1903.12470)
  - primary source о том, как telemetry loss может смещать результаты эксперимента.
- [From Augmentation to Decomposition: A New Look at CUPED in 2023](https://arxiv.org/abs/2312.02935)
  - современный primary source по CUPED как variance-reduction подходу и его связи с
  pre-experiment covariates.

При разработке конкретного урока API нужно сверять с locked environment репозитория, а
не только с последней online-документацией.

## Единая экспериментальная задача и данные

Фаза использует тот же вымышленный подписочный сервис с маркетплейсом дополнительных
товаров. Рабочий вопрос интеграционного проекта: «Команда хочет раскатить новый paywall
и onboarding hint для Android: ранняя активация должна вырасти, но нельзя ухудшить
жалобы, отмены подписки и refund rate. Можно ли запускать, держать эксперимент дольше,
откатывать или итеративно менять продукт?»

Фаза не зависит от файлов фазы 08 как от runtime-входа: она создает свой совместимый
experiment extract, чтобы уроки можно было проходить автономно. Семантически данные
остаются в той же вселенной.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `experiments` | один эксперимент и версия протокола | `experiment_id` |
| `experiment_variants` | один вариант внутри эксперимента | `experiment_id, variant_id` |
| `assignments` | одно стабильное назначение randomization unit в вариант | `experiment_id, assignment_unit_id` |
| `exposures` | один факт показа или активации варианта пользователю | `exposure_id` |
| `users` | один зарегистрированный пользователь | `user_id` |
| `events` | одно клиентское или серверное событие | `event_id` |
| `orders` | один платеж или заказ маркетплейса | `order_id` |
| `subscriptions` | один период подписки пользователя | `subscription_id` |
| `support_tickets` | одно обращение пользователя | `ticket_id` |
| `pre_experiment_metrics` | один user-level набор ковариат до старта эксперимента | `experiment_id, user_id` |
| `metric_observations` | одна рассчитанная user-level метрика в analysis window | `experiment_id, user_id, metric_id` |
| `interim_looks` | один запланированный или фактический промежуточный взгляд | `experiment_id, look_id` |

Базовые поля `assignments`:

| Поле | Смысл |
|---|---|
| `experiment_id` | идентификатор эксперимента |
| `assignment_unit_type` | `user_id`, `anonymous_id`, `device_id` или другой unit |
| `assignment_unit_id` | ключ единицы рандомизации |
| `user_id` | пользователь, если unit уже связан с identity |
| `variant_id` | `control`, `treatment` или другой объявленный вариант |
| `bucket` | стабильный hash bucket |
| `assigned_at` | момент назначения |
| `allocation_ratio` | ожидаемая доля трафика для варианта |
| `is_eligible` | флаг попадания в объявленную eligible population |
| `assignment_source` | локальный simulator, imported log или fixture |

Базовые поля `exposures`:

| Поле | Смысл |
|---|---|
| `exposure_id` | идемпотентный ключ exposure event |
| `experiment_id` | эксперимент |
| `assignment_unit_id` | единица назначения |
| `user_id` | пользователь после identity stitching |
| `variant_id` | вариант, реально увиденный пользователем |
| `exposed_at` | момент exposure |
| `exposure_event` | событие, которое считается началом влияния |
| `platform` | `web`, `ios` или `android` |
| `app_version` | версия приложения |
| `received_at` | момент доставки telemetry |

Профили данных:

- `tiny`: маленький валидный experiment baseline в Git для ручной сверки assignment,
  SRM, primary effect, bootstrap, CUPED и decision rule;
- `sample`: детерминированная локальная генерация для power simulation, peeking
  simulation, multiple-testing examples и segment heterogeneity;
- дефектные fixtures как минимальные мутации baseline, чтобы каждый failure mode был
  виден в одном тесте.

Заложенные свойства и failure modes:

- один пользователь получает два варианта из-за смены assignment key;
- exposure появляется до assignment или после outcome window;
- duplicated exposure event с тем же `exposure_id`;
- unknown/test users попадают в analysis population;
- telemetry loss на Android создает SRM без реального изменения трафика;
- late-arriving exposures ломают expected allocation на промежуточном срезе;
- pre-experiment covariate imbalance при некорректном bucketing;
- interference: household/device или shared account влияет на соседнего пользователя;
- underpowered experiment с красивым, но бесполезно широким interval;
- skewed revenue и zero-inflated metrics ломают наивный mean-only анализ;
- ratio metric с плавающим denominator дает lift другого смысла, чем user-level mean;
- CUPED использует post-treatment covariate и создает leakage;
- secondary metrics и post-hoc segments дают ложный успех после cherry-picking;
- незапланированные interim looks увеличивают false positive rate;
- guardrail deterioration при положительном primary lift;
- segment-specific effect на Android при нейтральном aggregate effect.

## Контракт experiment protocol

Каждый урок работает через machine-readable protocol. Он фиксирует методологию до
расчета и не дает менять правила после просмотра результатов:

```text
experiment_id
title
product_hypothesis
statistical_hypotheses
owner
decision_owner
variants
eligible_population
randomization_unit
analysis_unit
assignment_key
traffic_allocation
exposure_event
start_at
planned_end_at
metric_freeze_at
primary_metric
guardrail_metrics
secondary_metrics
exploratory_metrics
metric_windows
pre_experiment_covariates
alpha
power
minimum_detectable_effect
minimum_runtime_days
sample_size_plan
aa_srm_policy
multiple_testing_policy
peeking_policy
cuped_policy
segment_policy
decision_rule
rollback_rule
known_risks
limitations
```

Protocol не должен становиться декоративным JSON. Любой расчет в фазе обязан ссылаться
на его поля: если metric, population, alpha, segment family или interim look не объявлены
заранее, результат помечается как exploratory или блокируется для решения.

## Интеграционный мини-проект

`10/11` собирает поставку:

```text
experiment-decision-package/
├── protocol/
│   ├── experiment-protocol.json
│   └── metric-specs.json
├── assignment/
│   ├── randomization-spec.json
│   ├── assignments.csv
│   ├── exposure-audit.json
│   ├── aa-report.json
│   └── srm-report.json
├── planning/
│   ├── power-plan.json
│   ├── mde-grid.csv
│   └── power-curve.png
├── analysis/
│   ├── primary-effects.csv
│   ├── guardrail-effects.csv
│   ├── bootstrap-intervals.json
│   ├── cuped-effects.csv
│   ├── multiple-testing.json
│   ├── peeking-audit.json
│   └── heterogeneity.csv
├── quality/
│   ├── data-quality.json
│   ├── telemetry-loss.json
│   └── assumption-checks.json
├── report.md
├── decision.json
└── manifest.json
```

Пакет обязан:

- связать продуктовую гипотезу, вариант, primary metric, guardrails и decision rule;
- показать stable assignment: один eligible randomization unit получает один вариант;
- разделить assignment, exposure и outcome windows;
- проверить A/A, SRM, telemetry loss, duplicate exposures, unknown users, late arrivals
  и temporal leakage;
- доказать, что experiment достаточно мощный для заявленного MDE или явно признать
  inconclusive result;
- рассчитать effect size как absolute и relative lift с interval, p-value и assumptions;
- для skewed/ratio metrics показать bootstrap/permutation sensitivity;
- применить CUPED только к pre-treatment covariate и показать variance reduction;
- применить multiple-testing policy к объявленной metric family;
- зафиксировать, были ли interim looks и соответствует ли decision predeclared peeking
  policy;
- отделить predeclared segment analysis от exploratory findings;
- проверить guardrails до положительного launch decision;
- выпустить решение из ограниченного набора: `launch`, `hold`, `rollback`, `iterate`,
  `inconclusive`;
- связать каждый claim в `report.md` с artifact id, metric id и check id;
- выпустить SHA-256 manifest всех переданных файлов и параметров генерации данных.

## Проверяемость

- Tiny-profile содержит ручные ожидаемые ответы для assignment buckets, variant counts,
  SRM chi-square, primary lift, bootstrap interval seed, CUPED adjustment и final
  decision.
- Assignment tests проверяют stable hashing, allocation ratio, eligibility, duplicate
  assignment, multiple variants per unit и assignment/exposure ordering.
- A/A tests проверяют null distribution, p-value uniform sanity и отсутствие ложного
  decision signal на baseline.
- SRM tests блокируют analysis при несоответствии expected allocation и фактических
  variant counts, особенно при platform-specific telemetry loss.
- Power tests сверяют formula-based sizing с simulation tolerance и запрещают
  интерпретировать underpowered result как отрицательный эффект.
- Effect tests проверяют user-level denominator, Welch/proportion assumptions,
  absolute/relative lift и guardrail direction.
- Bootstrap tests фиксируют `rng`, `n_resamples`, resampling unit, paired denominator
  mode и degenerate/zero-inflated diagnostics.
- CUPED tests запрещают post-treatment covariates, missing covariate leakage и adjustment
  без variance-reduction report.
- Multiple-testing tests проверяют metric families, adjusted p-values, gatekeeping и
  exploratory flags.
- Peeking tests симулируют inflated false positive rate при незапланированных looks и
  проверяют заранее объявленный monitoring schedule.
- Segment tests проверяют predeclared dimensions, minimum cell size, interaction checks и
  запрет launch decision на одном post-hoc сегменте.
- Final package test проверяет существование всех файлов, ссылки claims на artifacts,
  consistency `decision.json` с protocol decision rule и checksum manifest.
