# История изменений

Здесь фиксируются заметные изменения программы, готовых уроков, сайта и контрактов
репозитория. Новые записи добавляются сверху. Формат основан на
[Keep a Changelog](https://keepachangelog.com/), но курс не обещает строгую семантическую
версионизацию до первого стабильного выпуска.

## [Unreleased]

### Добавлено

- Урок `13/11` «Causal workflow и границы автоматизации» с
  `causal_workflow_spec.json`, `causal_study_package.json`,
  `checksum_manifest.json`, CLI `causal_study_package_builder.py`, интеграцией 15
  upstream artifacts фазы 13, DoWhy-compatible workflow trace
  `model -> identify -> estimate -> refute`, явной границей автоматизации,
  EconML scope audit, запретом pooling разных estimands, финальной claim policy,
  которая блокирует single strong causal claim, и 14 behavioral tests.
- Урок `13/10` «Sensitivity analysis и falsification checks» с
  `sensitivity_spec.json`, `sensitivity_report.json`, CLI
  `sensitivity_refutation_suite.py`, placebo treatment/outcome checks,
  negative-control outcome, upstream DiD placebo propagation, omitted-confounding
  sensitivity grid, cross-design estimate comparison, no-pooling policy для разных
  estimands, claim policy с блокировкой single strong causal effect statement и 15
  behavioral tests.
- Урок `13/09` «RDD и instrumental variables: дизайн до оценки» с
  `quasi_experiment_spec.json`, `quasi_experiment_report.json`, CLI
  `quasi_experiment_design_auditor.py`, fuzzy RDD around friction-score cutoff,
  local bandwidth/density/continuity checks, sharp-vs-fuzzy candidate policy, IV first
  stage, reduced form, Wald LATE, observed balance screen, LATE-not-ATE claim policy,
  warnings по diagnostic-only tiny RDD и непроверяемым exclusion/monotonicity assumptions
  и 16 behavioral tests.
- Урок `13/08` «Difference-in-Differences» с `did_spec.json`,
  `did_report.json`, CLI `did_analyzer.py`, региональным rollout design,
  manual 2x2 DiD north versus not-yet-treated south, saturated regression
  reconciliation, pretrend slope check, fake pre-period и composition placebo checks,
  event-study table, sparse-tail warning, TWFE diagnostic-only warning для staggered
  adoption, limited claim policy и 17 behavioral tests.
- Урок `13/07` «Propensity weighting и doubly robust оценка» с
  `ipw_aipw_spec.json`, `ipw_aipw_report.json`, CLI `ipw_aipw_estimator.py`,
  ridge propensity scoring, stabilized IPW, Horvitz-Thompson и Hájek estimates,
  AIPW residual correction, overlap/tail diagnostics, weight и effective-sample-size
  report, trimming sensitivity, stress tests для misspecified treatment/outcome models,
  bad-control/source coverage gates, claim policy и 19 behavioral tests.
- Урок `13/06` «Matching и баланс ковариат» с `matching_spec.json`,
  `matching_report.json`, CLI `matching_pipeline.py`, nearest-neighbor ATT matching
  по pre-treatment covariates, standardized Euclidean distance, caliper, replacement
  policy, common-support audit, matched pairs, balance table, love plot data, bad-control
  gates, claim policy и 16 behavioral tests.
- Урок `13/05` «Regression adjustment и g-formula» с `g_formula_spec.json`,
  `g_formula_estimate_report.json`, CLI `g_computation_estimator.py`, ручной OLS
  g-computation, сверкой со statsmodels, standardized potential outcomes, ATE/ATT,
  diagnostics по LPM bounds, support/extrapolation, bad-control/source coverage, claim
  policy и 16 behavioral tests.
- Урок `13/04` «Colliders, mediators и selection bias» с
  `bad_control_policy.json`, `candidate_control_actions.json`,
  `bad_control_selection_audit.json`, CLI `bad_control_selection_auditor.py`,
  проверками mediator, collider, selection filter, treatment descendant, outcome
  leakage, assignment-mechanism controls, population-change policy, allowed baseline
  handoff для будущих estimators и 16 behavioral tests.
- Урок `13/03` «Confounders и backdoor adjustment» с
  `confounder_inventory.json`, `adjustment_set_spec.json`,
  `backdoor_adjustment_audit.json`, CLI `backdoor_adjustment_auditor.py`, проверками
  measured/unmeasured confounders, source fields в data contract, active backdoor paths,
  candidate adjustment set statuses, primary observed baseline recommendation,
  forbidden mediator/collider/selection controls, claim policy при remaining unmeasured
  confounding и 15 behavioral tests.
- Урок `13/02` «Причинные DAG и идентификация» с machine-readable
  `causal_dag.json`, `identification_map.json`, standalone CLI
  `causal_dag_validator.py`, `dag_audit.json`, проверками acyclicity, temporal order,
  d-separation, active backdoor paths, association-vs-intervention, mediator/collider/
  selection bad controls, преждевременного estimator и ложного `identified` status и
  17 behavioral tests.
- Урок `13/01` «Причинный вопрос и estimand» с общим deterministic causal dataset фазы,
  target trial-style `causal_question.json`/`target_trial_spec.json`/`estimand.json`,
  CLI `causal_question_validator.py`, проверками ATE/ATT/LATE population semantics,
  time zero, treatment versions, grace period, outcome windows, causal assumptions,
  запретом post-treatment eligibility и premature effect claims и 14 behavioral tests.
- Фаза 13 «Причинный анализ» спроектирована целиком: 11 уроков на 15,5 часа,
  causal question и estimand, DAG/identification, backdoor adjustment, bad controls,
  regression adjustment/g-formula, matching, IPW/AIPW, DiD, RDD/IV design audit,
  sensitivity/falsification и интеграционный `causal-study-package` с DoWhy automation
  audit и явной границей применения EconML.
- Урок `11/11` «Локальный проект с dbt-duckdb» с финальным пакетом
  `analytics-mart-dbt`: sources, staging/intermediate/mart models, macros, 87 dbt data
  tests, incremental fact, snapshot, docs/exposure lineage, SQLFluff lint на 22
  SQL-файлах, `target-artifacts/manifest.json`/`catalog.json`/`run_results.json`,
  `lineage-summary.json`, quality reports, `report.md`, SHA-256 checksum manifest,
  CLI-packager `analytics_mart_packager.py` и 8 behavioral tests.
- Урок `11/10` «SQLFluff и единый стиль» с dbt-проектом `sqlfluff_project`,
  `.sqlfluff` для DuckDB/dbt templater, `.sqlfluffignore` для generated artifacts,
  safe local `profiles.yml`, cleaned SQL models/tests, raw-templater bad style example,
  live `sqlfluff lint` на 22 SQL-файлах, machine-readable lint report, CLI-аудитором
  `sqlfluff_quality_gate.py`, разделением style gate и `dbt test` semantic gate и
  10 behavioral tests; в dev dependencies добавлены `sqlfluff==3.5.0` и
  `sqlfluff-templater-dbt==3.5.0`.
- Урок `11/09` «Документация и lineage» с dbt-проектом `documentation_project`,
  docs blocks, descriptions для sources/models/columns/snapshots/singular tests,
  exposure `customer_revenue_health_dashboard`, decision claims, owners, live
  `dbt docs generate`, проверкой `manifest.json`/`catalog.json`, lineage до mart/fact/SCD
  models и 10 behavioral tests.
- Урок `11/08` «Snapshots и история изменений» с dbt-проектом `snapshot_project`,
  YAML snapshot `subscription_status_snapshot`, SCD type 2 моделью
  `int_subscription_history`, `unique_key=subscription_id`, `strategy=check`,
  `updated_at`, явным `check_cols` без шумного `updated_at`, `dbt_valid_to_current`,
  runbook для schedule/hard deletes, live двумя `dbt snapshot` циклами и 10
  behavioral tests.
- Урок `11/07` «Инкрементальные модели» с dbt-проектом `incremental_project`,
  incremental fact-моделью `fct_order_revenue_daily`, `unique_key='revenue_date'`,
  strategy `delete+insert`, late-arrival window на 2 дня, `on_schema_change='fail'`,
  `incremental_contract` в `models/properties.yml`, full-refresh/backfill playbook,
  source-level reconciliation test, live initial full refresh + incremental late-arrival
  сценарий без дублей и 9 behavioral tests.
- Урок `11/06` «Jinja и macros без злоупотребления» с dbt-проектом
  `macro_project`, 5 documented low-level macros, `macros/properties.yml`,
  compiled SQL review checklist, live `dbt parse`/`compile`/`run`/`test`, проверкой
  отсутствия Jinja в compiled models, запретом macro для customer health business logic,
  mart baseline audit и 10 behavioral tests.
- Урок `11/05` «Data tests» с dbt-проектом `data_test_project`, 64 generic
  data tests, 3 singular tests, source freshness, разделением blocking contract gates и
  warning diagnostics, live `dbt parse`/`run`/`source freshness`/`test`, JSON-аудитором
  `dbt_test_reporter.py` и 11 behavioral tests.
- Урок `11/04` «Модели и materializations» с dbt-проектом
  `materialization_project`, 13 staging/intermediate/mart моделями, policy
  `view`/`table`/`ephemeral` в `properties.yml`, live `dbt parse`/`compile`/`run`,
  physical relation audit, compiled ephemeral CTE check, independent mart
  reconciliation и 10 behavioral tests.
- Урок `11/03` «Sources, refs и зависимости» с dbt-проектом `source_ref_project`,
  объявлением 8 raw tables как `sources`, staging-моделями через `source()`,
  downstream graph через `ref()`, source freshness smoke check, manifest lineage audit,
  запретом hardcoded `raw_*` references и 10 behavioral tests.
- Урок `11/02` «Структура dbt-проекта» с `dbt_project_skeleton/`,
  `profiles.yml.example`, smoke graph `staging -> intermediate -> marts`,
  командами `dbt debug`/`dbt parse`/`dbt compile`, CLI-аудитором структуры проекта и
  11 behavioral tests; в locked runtime добавлены `dbt-core==1.11.11` и
  `dbt-duckdb==1.10.1`.
- Урок `11/01` «Слои и контракты аналитических данных» с первым tiny extract фазы 11,
  `layer_contract.json`, `mart_design_brief.md`, CLI-аудитором layer contract,
  проверками raw/staging/intermediate/mart boundaries, source lineage, key tests,
  mart publication contract и design brief.
- Фаза 11 «Analytics Engineering» спроектирована целиком: 11 уроков на 15 часов,
  data layers, dbt project, sources/refs, materializations, data tests, Jinja macros,
  incremental models, snapshots, documentation/lineage, SQLFluff и интеграционный
  локальный `analytics-mart-dbt` package на dbt-duckdb.
- Урок `10/09` «Подглядывание и последовательный анализ» с
  `peeking_audit.py`, `peeking_policy.json`, `sequential_monitoring_report.json`,
  `monitoring_schedule.csv`, `peeking_simulation.csv`, O'Brien-Fleming/Lan-DeMets
  alpha spending, simulation-based false positive inflation и блокировкой решения при
  unplanned decision looks.
- Урок `10/08` «Множественные проверки» с
  `multiple_testing_policy_checker.py`, `multiple_testing_policy.json`,
  `multiple_testing_report.json`, `adjusted_results.csv`, сверкой ручных
  Bonferroni/Holm/FDR поправок со statsmodels/SciPy, gatekeeping primary/guardrail/
  secondary и запретом launch decision по post-hoc exploratory сегментам.
- Урок `10/07` «Снижение дисперсии и CUPED» с
  `experiment_cuped_adjuster.py`, `cuped_spec.json`, `cuped_effects.csv`,
  `adjusted_observations.csv`, `variance_reduction_report.json`, проверками
  pre-treatment ковариат, missingness, post-treatment leakage, variance reduction и
  explicit skip для ratio/sparse metrics.
- Урок `10/06` «Bootstrap в экспериментах» с
  `experiment_bootstrap_analyzer.py`, `bootstrap_spec.json`,
  `bootstrap_intervals.json`, `bootstrap_distribution.csv`,
  `resampling_manifest.json`, fixed RNG, resampling по `user_id`, permutation
  sensitivity и paired denominator handling для ratio metrics.
- Урок `10/05` «Сравнение средних и долей» с
  `experiment_effect_calculator.py`, `effect_spec.json`, user-level
  `metric_observations.csv`, `effect_results.csv`, `assumption_checks.json`, расчетом
  proportions, means и ratio metrics, guardrail watch status и запретом launch decision
  по secondary-only signal.
- Урок `10/04` «MDE, мощность и размер выборки» с `power_planner.py`,
  `power_spec.json`, `power_plan.json`, `mde_grid.csv`, `power_curve.png`, расчетом
  sample size для proportions и means, simulation sanity check и upstream health gate.
- Урок `10/03` «A/A-тест и Sample Ratio Mismatch» с
  `randomization_health.py`, committed health report, assignment/exposure SRM,
  telemetry-loss gate, pre-treatment covariate balance и exact permutation A/A
  pseudo-outcome checks.
- Урок `10/02` «Единица рандомизации» с deterministic `assignment_engine.py`,
  `randomization_spec.json`, assignment/exposure fixtures, проверками stable hash,
  one-unit-one-variant, eligibility, exposure timing, balance и interference risk.
- Урок `10/01` «Гипотеза и целевая метрика» с первым experiment extract фазы 10,
  pre-registered `experiment_protocol.json`, `metric_specs.json`,
  CLI-валидатором experiment protocol, проверками variants/allocation, metric roles,
  windows, alpha/power/MDE, CUPED covariates, guardrails и decision rule.
- Фаза 10 «Эксперименты и A/B-тесты» спроектирована целиком: 11 уроков на
  15,75 часа, experiment protocol, randomization unit, A/A, SRM, MDE/power,
  effect estimation, bootstrap, CUPED, multiple testing, peeking, heterogeneity и
  итоговый `experiment-decision-package`.
- Полностью завершена фаза 09 «Прикладная статистика»: 10 уроков, 13,75 часа,
  112 behavioral tests и финальный `statistical-evidence-report/` package с sampling
  audit, distribution cards, point estimates, bias/variance simulation, formula и
  bootstrap intervals, correlation audit, OLS inference, regression diagnostics,
  robust/nonparametric sensitivity checks, figures, report и SHA-256 manifest.
- Уроки `09/04`–`09/10`: `bias-variance-simulator`, `confidence-interval-calculator`,
  `bootstrap-interval-builder`, `correlation-auditor`, `ols-inference-runner`,
  `regression-diagnostics-checker` и `robust-evidence-packager`; statsmodels 0.14.6
  и patsy 1.0.2 добавлены в locked runtime для regression inference.
- Урок `09/03` «Оценки и свойства оценок» с `estimator-runner`,
  machine-readable estimator spec, upstream sampling audit/distribution-card checks,
  naive и weighted point estimates для proportion/mean/quantile/rate, standard error
  diagnostics и 17 behavioral tests.
- Урок `09/02` «Распределения как модели» с SciPy-based
  `distribution-card-builder`, карточками Bernoulli/binomial activation,
  lognormal positive revenue/duration, Poisson count diagnostics, support checks,
  limitations и 13 behavioral tests; SciPy 1.17.1 добавлен в locked runtime.
- Урок `09/01` «Популяция, выборка и механизм отбора» с общим dataset фазы 09
  (`population_users`, `sampling_frame`, `sample_observations`, `segment_reference`),
  CLI-аудитором sampling frame, coverage/non-response/weight diagnostics и 10
  behavioral tests.
- Фаза 09 «Прикладная статистика» спроектирована целиком: 10 уроков на 13,75 часа,
  самостоятельная user-level статистическая задача для product и ML-маршрутов, sampling
  frame, estimator specs, intervals, bootstrap, correlation audit, OLS diagnostics,
  robust sensitivity checks и интеграционный `statistical-evidence-report`.
- Полностью завершена фаза 08 «Продуктовая аналитика»: 11 уроков, 12-16 часов,
  единая событийная модель продукта и интеграционный `product-problem-investigation`
  package с metric/tracking contracts, metric tables, anomalies, report,
  recommendation и checksum manifest.
- Урок `08/11` «Бизнес-вывод и рекомендация» с CLI-builder'ом
  `product-problem-investigation/`, evidence-map, machine-readable recommendation,
  запретом unsupported causal claims, проверкой artifact paths/metric IDs и SHA-256
  manifest.
- Урок `08/10` «Аномалии продуктовых метрик» с anomaly spec, CLI-детектором
  `data_quality`/`composition`/`calendar_effect`/`product_signal` candidates,
  freshness/duplicate/late-arrival/tracking completeness gates и запретом product-signal
  интерпретации до прохождения quality gates.
- Урок `08/09` «Guardrail-метрики» с guardrail spec,
  CLI-калькулятором support ticket, subscription cancel и refund rates,
  `risk_direction=up_is_bad`, thresholds, complete-window policy, decision status и
  overall-блокировкой rollout при breached guardrails.
- Урок `08/08` «Сегментация без самообмана» с segmentation spec,
  CLI-калькулятором segment activation rates, predeclared/exploratory dimensions,
  minimum cell size, platform decomposition на within-segment/composition effects и
  запретом causal claims без эксперимента.
- Урок `08/07` «Выручка, ARPU и LTV» с monetization spec,
  CLI-калькулятором realized revenue, ARPU, ARPPU и fixed-window cohort LTV,
  paid/refunded/pending order semantics, cancelled subscriptions, complete-window
  policy и защитой от many-to-many revenue joins.
- Урок `08/06` «Retention и возвращаемость» с retention spec, CLI-калькулятором
  `exact_day`/`on_or_after` retention, fixed denominator, age_day 1-7,
  complete-window policy, дедупликацией событий и quality report.
- Урок `08/05` «Когортный анализ» с cohort spec, CLI-калькулятором daily cohort
  matrix, фиксированным denominator, age_day 0-7, complete/incomplete observation
  windows, дедупликацией событий и quality report для late arrivals.
- Урок `08/04` «Воронки и неоднозначность конверсии» с funnel spec,
  CLI-калькулятором closed funnels, strict/loose ordering, units `user_id`,
  `session_id`, `user_day`, conversion window, дедупликацией событий и quality report
  для late arrivals.
- Урок `08/03` «Активность и активная аудитория» с activity spec, CLI-расчетом
  DAU/rolling active users, eligible denominator, business timezone, исключением test
  users, дедупликацией событий и флагами неполных окон.
- Урок `08/02` «Событийная модель продукта» с machine-readable tracking plan,
  CLI-валидатором event names, versions, required properties, identity policy,
  duplicates, late arrivals, mobile `app_version` и связей событий с metric specs.
- Урок `08/01` «Дерево метрик» с продуктовым metric tree, machine-readable
  metric specs, CLI-валидатором ролей outcome/input/guardrail, знаменателей,
  окон, source tables, validation checks и направления риска guardrail-метрик.
- Для фазы 08 добавлен детерминированный продуктовый tiny dataset: users, sessions,
  events, subscriptions, orders, support tickets, release calendar, contract и
  воспроизводимый генератор.
- Фаза 08 «Продуктовая аналитика» спроектирована целиком: 11 уроков на 12-16 часов,
  единая событийная модель подписочного продукта, tracking plan, metric specs,
  product metrics от активности до LTV, guardrails, диагностика аномалий и
  интеграционное исследование продуктовой проблемы.
- Полностью завершена фаза 07 «Надежная аналитика»: 10 уроков, 825 минут,
  60 behavioral tests и единый order-quality pipeline от инвариантов и минимальных
  дефектов до Hypothesis, Pandera, Pydantic, SQL, golden regression, monitoring и
  атомарной публикации immutable mart.
- Корневой locked dependency contract дополнен Hypothesis 6.155.2, Pandera 0.31.1 и
  Pydantic 2.13.4.
- Фаза 07 «Надежная аналитика» спроектирована целиком: 10 последовательных уроков на
  13,75 часа, единый order-quality pipeline, матрица дефектов, Hypothesis, Pandera,
  Pydantic, SQL-reconciliation, regression tests и интеграционный quality gate.
- Урок `07/01` «Инварианты аналитического расчета» с ручным контрольным путем,
  CLI-проверкой структурных и алгебраических правил и behavioral tests.
- Полностью завершена фаза 06 «EDA и визуальное мышление»: 11 уроков, 91 behavioral
  test и артефакты от visual question brief и data audit до статических, интерактивных
  и декларативных визуализаций и интеграционного EDA-report с checksum manifest.
- Корневой locked dependency contract дополнен Matplotlib 3.11.0, Seaborn 0.13.2,
  Plotly 6.8.0 и Altair 6.2.1.
- Урок `06/01` «Вопрос раньше графика» с контрактом visual question brief,
  rubric выбора представления, предупреждением о причинной формулировке и девятью
  behavioral tests.
- Фаза 06 «EDA и визуальное мышление» спроектирована целиком: 11 последовательных
  уроков на 15,5 часа, единый `user_journeys` dataset, явные границы Matplotlib,
  Seaborn, Plotly и Altair и интеграционный воспроизводимый EDA-report.
- Полностью завершена фаза 05 «Источники и форматы данных»: 11 уроков, 90 behavioral
  tests, 14 детерминированных fixtures и самостоятельные артефакты от CSV/Excel/JSON
  contracts до устойчивого загрузчика с raw cache, SHA-256 и partitioned Parquet.
- Корневой locked dependency contract дополнен openpyxl 3.1.5, Requests 2.34.2,
  Beautiful Soup 4.15.0, SQLAlchemy 2.0.50 и PyArrow 24.0.0.
- Урок `05/01` «CSV и неоднозначность типов» с явным encoding/dialect/schema-контрактом,
  CP1251 fixtures, аудитором повреждённых строк и девятью behavioral tests.
- Фаза 05 «Источники и форматы данных» спроектирована целиком: 11 последовательных
  уроков на 14 часов с контрактами файловых форматов, устойчивым получением внешних
  данных, Arrow/Parquet-поставкой и интеграционным загрузчиком с кешем и checksum.
- Полностью завершена фаза 04 «SQL и DuckDB»: 12 уроков, 98 behavioral tests,
  самостоятельные CLI и SQL-артефакты от grain-аудита до когорт, планов запросов и
  интеграционной поставки `order_mart`/`user_summary` с checksum-manifest.
- Урок `04/01` «Grain, ключи и связи» с ручной моделью проверки ключа,
  DuckDB-аудитором primary/foreign keys, девятью behavioral tests и JSON quality gate.
- Фаза 04 «SQL и DuckDB» спроектирована целиком: 12 последовательных уроков на
  17,5 часа с измеримыми результатами, артефактами и интеграционной SQL-витриной.
- DuckDB 1.5.3 добавлен в корневой locked dependency contract курса.
- Для фазы 04 добавлены детерминированный tiny-набор `users`, `orders`,
  `order_items`, `events` и локальный sample-профиль более чем на 500 тысяч строк.
- Полностью завершена фаза 03 «pandas и табличные данные»: 11 уроков от модели
  DataFrame и nullable dtype до безопасных join, временных зон, method chaining и
  интеграционной order mart с manifest.
- Для фазы 03 добавлен 91 behavioral test и 11 самостоятельных артефактов: инспекторы
  grain и dtype, безопасные фильтры, преобразования, агрегации, merge, reshape,
  нормализаторы времени и категорий, pipeline и mart builder.
- Фаза 03 «pandas и табличные данные» полностью спроектирована: для 11 уроков
  зафиксированы тип, время, зависимости, измеримый результат и артефакт; `03/11`
  назначен интеграционным мини-проектом.
- Детерминированный tiny-набор `users`, `orders` и `order_items` для фазы 03 с
  машинным контрактом, известными дефектами и SHA-256 манифестом.
- pandas 3.0.3 добавлен в корневой locked dependency contract курса.
- Полностью завершена фаза 02 «NumPy и численные данные»: девять уроков от модели
  `ndarray` и shape-контрактов до воспроизводимых симуляций, benchmark и численного
  quality gate.
- Уроки `02/02`–`02/04` с предиктором форм, аудитором dtype и функциями числовой
  фильтрации с явной семантикой view/copy.
- Уроки `02/05`–`02/07` с ручной проверкой broadcasting, агрегатами по осям и
  симулятором распределения выборочного среднего на `numpy.random.Generator`.
- Уроки `02/08`–`02/09` с воспроизводимым benchmark векторизации и интеграционным
  quality gate для tolerances, деления, overflow и точности суммирования.
- Урок `02/01` «ndarray и модель массива» с разбором `ndim`, `shape`, `size`,
  `dtype`, ручной проверкой прямоугольной формы и CLI-инспектором числовых массивов.
- Корневой `uv.lock` и единый dependency-контракт курса: NumPy 2.4.6,
  pytest 9.0.3, Ruff 0.15.17 и PyYAML 6.0.3; GitHub Pages CI теперь
  восстанавливает locked environment перед проверками.
- Урок `01/09` «Автоматическая проверка в CI» со standalone GitHub Actions
  project, locked uv sync, минимальными permissions и self-audit workflow.
- Урок `01/08` «Первые проверки с pytest» с behavioral suite для воронки,
  параметризацией, fixtures, boundaries и domain errors.
- Урок `01/07` «Единый стиль и Ruff» с явной rule policy, safe fixes,
  formatter gate и тестами на настоящем Ruff.
- Урок `01/06` «От ноутбука к модулям и скриптам» с importable package,
  проверяемым data contract и JSON CLI.
- Урок `01/05` «Воспроизводимые ноутбуки» с чистым notebook, реальным
  top-down execution и CLI-аудитом скрытого состояния.
- Урок `01/04` «Jupyter, kernels и состояние» с диагностическим notebook,
  разбором kernelspec и CLI-сверкой фактического Python-процесса.
- Урок `01/03` «pyproject.toml как контракт проекта» с разделением runtime/dev
  зависимостей, настройками инструментов и CLI-аудитом manifest.
- Урок `01/02` «Окружения и зависимости с uv» с настоящим lock/sync workflow,
  восстановлением `.venv` и CLI-проверкой locked-окружения.
- Урок `01/01` «Версии Python и совместимость» с контрактом `requires-python`,
  selector-файлом и CLI для проверки фактического интерпретатора и матрицы версий.
- Урок `00/06` «Секреты и безопасная работа с данными» с env-контрактом,
  классификацией данных и CLI для создания и проверки безопасного шаблона проекта.
- Урок `00/05` «Ветки, pull request и ревью» с локальным feature-branch сценарием,
  трёхточечным diff и CLI-пакетом для подготовки аналитического ревью.
- Урок `00/04` «Git: история аналитического проекта» с локальным Git-сценарием и CLI для
  проверки истории, `.gitignore` и сфокусированности commits.
- Урок `00/03` «Терминал и файловая система» с Bash CLI для воспроизводимого аудита
  файлов, тестами необычных имён и разбором безопасных pipelines.
- Полностью завершена фаза 01 «Воспроизводимый проект»: девять уроков от версии Python
  и lockfile до Ruff, pytest и CI.
- Публичный минимум репозитория: кодекс поведения, шаблоны issue и pull request, индекс
  проектной документации.
- Навигация для учащихся и контрибьюторов в корневом README.

## [0.1.0] — 2026-06-12

### Добавлено

- Единая программа из 19 фаз и 201 урока с пятью профессиональными маршрутами.
- Завершенные уроки `00/01` «Карта профессии аналитика» и `00/02` «Диагностика Python и
  SQL».
- Контракт урока с исполняемым кодом, тестами, квизом, артефактом и дополнительным
  чтением.
- Генераторы дорожной карты, страниц фаз, каталога артефактов и данных сайта.
- Standalone static-сайт с дорожной картой, каталогом, маршрутами, глоссарием и локальным
  прогрессом.
- GitHub Pages workflow и проверки структуры курса.
- Агентские навыки для определения стартового уровня и проверки понимания фазы.
- Handoff-контекст для продолжения разработки в новых чатах.

### Изменено

- Исходная tool-first программа преобразована в problem-first курс с общим ядром,
  специализациями и несколькими итоговыми маршрутами.
