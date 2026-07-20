# Статус проекта

> Этот файл — handoff для нового чата. Сначала проверьте `git status`: рабочее дерево
> может содержать более свежие изменения.

**Обновлено:** 21 июля 2026
**Ветка:** `main`
**Базовый коммит перед текущим этапом:** `5547e7a3` — переработка урока производных столбцов pandas

Все 198 нумерованных уроков курса завершены. Публичный сайт размещён на
`https://datascience.xyz/courses/analyst-tools/` и публикует отдельную статическую страницу
для каждого урока. Пользовательский `site/Archive.zip` не входит в генерацию и должен
оставаться отдельным от изменений курса.

В предыдущем коммите завершен последовательный педагогический аудит фазы 02.
После индексации добавлен новый урок `02/05` о сборке, сортировке и согласованности
массивов: он закрывает `concatenate` / `stack`, единую устойчивую перестановку связанных
значений, `unique`, `argmin` / `argmax`, dtype и копирование. Прежние уроки `02/05`–`02/09`
сдвинуты на позиции `02/06`–`02/10`, а зависимость фазы pandas обновлена. В агрегации
встроено различие редукции, накопления и конечной разности; в уроке о векторизации
`np.vectorize` перенесен из дополнительного чтения в основное объяснение как анти-ловушка.

В предыдущем коммите повторяющийся процесс аудита фаз 00–02 оформлен как проектный скилл
`.agents/skills/audit-course-lesson`: он работает с одним уроком, сначала проверяет его
необходимость и связность, строит доказательную карту предпосылок по пройденным урокам,
разделяет аудит и реализацию, выбирает код по наблюдаемому результату, перестраивает
чтение в 10 аннотированных источников и ограничивает проверки затронутым объемом.

В предыдущем коммите переработан урок `03/01` «DataFrame, Series и индексы». Он связывает
позиционную модель NumPy с маркированными осями pandas, показывает отношение `DataFrame`
и `Series`, label alignment и границу между техническим индексом, grain и кандидатным
бизнес-ключом. CLI-инспектор требует простой или составной ключ, сохраняет evidence при
провале и различает коды корректного контракта, нарушения данных и невалидного запуска.

В предыдущем коммите переработан урок `03/03` «Выбор строк и столбцов» с
опорой на маркированные оси `03/01`, dtype-контракт и `pd.NA` из `03/02` и булевы маски
NumPy из `02/04`. Урок теперь различает форму `Series` и одно-столбцового `DataFrame`,
выбор по меткам и позициям, правые границы `loc`/`iloc`, выравнивание масок и строгий
контракт их происхождения. Nullable-маска сохраняется до отчёта по `True`, `False` и
`NA`; только затем применяется явная политика `exclude` или `error`. Артефакт больше не
читает и не очищает CSV повторно: он принимает уже типизированный `DataFrame`, проверяет
только использованные столбцы, выбирает названные столбцы и помечает строки на копии одним
`loc`-присваиванием. Практика покрыта 19 behavioral tests, а путеводитель фазы
синхронизирован.

В предыдущем коммите дополнительное чтение `03/03` расширено с трех до десяти
аннотированных материалов. Подборка содержит один русскоязычный обзор из Яндекс Хендбука
и девять актуальных официальных страниц pandas: вводный tutorial, общий контракт
индексирования, `loc`, `iloc`, nullable Boolean, `Series.isin`, `Index.equals`, duplicate
labels и Copy-on-Write. Яндекс Практикум и слабые русскоязычные пересказы не используются.

В предыдущем коммите переработан урок `03/04` «Производные столбцы:
арифметика, `where` и `mask`». Он теперь явно отделяет преобразование с сохранением grain
от выборки `03/03` и агрегации `03/05`, принимает уже типизированную таблицу товарных
позиций и подробно объясняет арифметику `Series`, выравнивание по индексу, nullable-dtype
и трехзначное условие. На примере pandas 3.0.3 показано, что `where(..., 0)` заменяет
значение и при `pd.NA` в условии, поэтому неизвестность восстанавливается отдельной
политикой. Из урока удалены повторный `pd.to_numeric`, строковая нормализация, `pd.cut`,
преждевременный `groupby`, CLI и лишний benchmark. Чистая функция сохраняет входной
объект, индекс, строки и исходные столбцы; 15 behavioral tests проверяют построчные
значения, границу, dtype, распространение `NA` и ошибки входного контракта. Дополнительное
чтение расширено до десяти проверенных материалов: двух русскоязычных учебных разделов
Яндекс Хендбука и практикума по таблицам pandas, а также восьми актуальных страниц
официальной документации pandas о производных столбцах, `NA`, nullable Boolean, `where`,
`mask`, `apply` и UDF.

В текущем незакоммиченном этапе переработан урок `03/05` «GroupBy и единица анализа» как
прямое продолжение `03/01`–`03/04`. Он принимает уже типизированные товарные позиции с
производным `line_total`, проверяет входной grain `(order_id, product_id)` и сворачивает
их до одной строки на `order_id`. Урок подробно разводит population и grain, ручной
`split -> apply -> combine`, `size` / `count` / `nunique`, пропуск в ключе и пропуск в
значении, сумму известных частей и строгий полный итог. Повторный `pd.to_numeric`,
строковая нормализация, paid-фильтр, `observed`, произвольный `GroupBy.apply` и CLI
удалены. Чистая функция `aggregate_order_items` сохраняет evidence неполноты, nullable
dtype и входной объект; 15 behavioral tests проверяют ручную сверку, новый grain,
reconciliation, полный, частичный, неизвестный и нулевой заказ и ошибки контракта.
Дополнительное чтение расширено до десяти проверенных материалов: двух полезных
русскоязычных объяснений и восьми англоязычных официальных или первичных источников о
grain, `split -> apply -> combine`, именованной агрегации, знаменателях, пропусках,
`min_count` и переносе модели в SQL.

Контракт урока по-прежнему выбирает форму практики по наблюдаемому результату:
`executable` требует behavioral tests, а `guided-artifact` — самостоятельный шаблон и
рубрику. Код не добавляется ради единообразия. Контракт дополнительного чтения допускает
от трёх до десяти аннотированных ссылок. Входной диагностики нет: все студенты начинают с
фазы 00, а подготовительные материалы по Python, SQL и статистике остаются необязательным
справочником.

Push и commit выполняются только по явной команде пользователя. Перед продолжением
проверьте актуальное состояние через `git status`.

## Цель

Собрать единый открытый курс по современным инструментам аналитика. Курс должен:

- сохранять структурную идеологию `ai-engineering-from-scratch`;
- поддерживать несколько профессиональных маршрутов внутри одной дорожной карты;
- завершать каждый урок проверяемым переиспользуемым артефактом;
- поставляться вместе со standalone static-сайтом в `site/`;
- работать после публикации на GitHub Pages или другом static hosting.

## Текущий снимок

- 19 фаз.
- 198 уроков в программе.
- 198 завершенных уроков.
- 0 уроков в статусе `designed`.
- 0 уроков остаются в статусе `planned`.
- Фазы 00–18 полностью завершены.
- Фаза 10 «Эксперименты и A/B-тесты» завершена: готовы уроки `10/01`–`10/11`.
- Фаза 11 «Analytics Engineering» завершена: 11 уроков на 900 минут; готовы уроки
  `11/01` «Слои и контракты аналитических данных», `11/02` «Структура dbt-проекта»,
  `11/03` «Sources, refs и зависимости», `11/04` «Модели и materializations»,
  `11/05` «Data tests», `11/06` «Jinja и macros без злоупотребления»,
  `11/07` «Инкрементальные модели», `11/08` «Snapshots и история изменений» и
  `11/09` «Документация и lineage», `11/10` «SQLFluff и единый стиль» и `11/11`
  «Локальный проект с dbt-duckdb».
- Фаза 12 «Производительность аналитики» завершена: 11 уроков на 915 минут,
  готовы `12/01` «Корректный benchmarking», `12/02` «CPU и memory profiling»,
  `12/03` «Память и типы данных», `12/04` «Projection и predicate pushdown»,
  `12/05` «Arrow memory model», `12/06` «DuckDB и данные больше памяти» и
  `12/07` «Polars expressions», `12/08` «Lazy execution и оптимизация»,
  `12/09` «Streaming и пакетная обработка» и `12/10` «Обмен между pandas, Arrow
  и Polars», `12/11` «Ibis как переносимый DataFrame API»,
  единая задача `customer_revenue_health_weekly`, benchmark protocol,
  Parquet/Arrow/DuckDB/Polars/Ibis и финальный multi-engine benchmark package.
- Фаза 13 «Причинный анализ» завершена: 11 уроков на 930 минут с causal question,
  estimand, DAG/identification, adjustment, matching, IPW/AIPW, DiD, RDD/IV,
  sensitivity и итоговым `causal-study-package`.
- Фаза 14 «Временные ряды» завершена: 12 уроков на 945 минут с временным индексом,
  resampling, leakage-free rolling features, temporal leakage audit, seasonal baseline,
  decomposition, ETS/ARIMA, rolling backtesting, forecast metrics, prediction intervals,
  anomaly policy и итоговым `time-series forecast package`.
- Фаза 15 «Прикладное машинное обучение» завершена: 15 уроков на 1170 минут с ML
  problem framing, train/validation/test split, metric/cost policy, preprocessing,
  scikit-learn Pipeline/ColumnTransformer, dummy/linear/tree/ensemble baselines,
  cross-validation, imbalance, probability calibration, leakage audit, segment error
  analysis и итоговым `ML baseline package`/model card.
- Фаза 16 «Табличный ML и интерпретация» завершена: 11 уроков на 900 минут с CatBoost
  baseline, categorical feature audit, early stopping, built-in/permutation/SHAP
  interpretation, segment and cost-sensitive decision gates, Optuna, MLflow ledger и
  итоговым `tabular-ml-interpretation-package`.
- Фаза 17 «Доставка аналитического результата» завершена: 12 уроков на 960 минут
  со stakeholder memo, XLSX workbook, Quarto HTML/PDF/DOCX reports, Plotly appendix,
  Streamlit app, cache/state/freshness, CLI, scheduled refresh, optional FastAPI/Docker
  и итоговым `stakeholder-delivery-package`; готовы уроки `17/01`–`17/12`.
- В фазе 18 готовы `18/01` «Выбор и ограничение задачи», `18/02` «Контракт и аудит
  данных», `18/03` «Baseline результата», `18/04` «Реализация проекта», `18/05`
  «Проверки и независимая валидация» и `18/06` «Peer review»: brief, data contract,
  baseline, implementation, independent verification и review closure стали
  последовательными gates перед defense.
- Урок `15/01` «Постановка ML-задачи» завершен: deterministic tiny churn-risk profile,
  `problem_spec.json`, `ml_scoring_snapshots.csv`, `ml_labels.csv`,
  `feature_source_inventory.csv`, CLI `ml-problem-spec-validator`,
  `ml_problem_readiness_report.json`, checks для business decision, prediction unit,
  target horizon/classes, feature availability, predeclared evaluation policies,
  no-causal-claim boundary, warning `class_imbalance_expected` и 13 behavioral tests.
- Урок `15/02` «Train, validation и test» завершен: shared tiny profile расширен до
  трех prediction-date blocks, добавлен `ml_split_manifest.csv`, CLI
  `ml-split-auditor`, `ml_split_report.json`, checks для eligible coverage,
  group isolation, chronological holdout, label horizon, validation/test role boundary,
  warning `tiny_split_expected` и 15 behavioral tests.
- Урок `15/03` «Метрики и стоимость ошибки» завершен: shared tiny profile дополнен
  `ml_candidate_scores.csv`, CLI `classification-metric-evaluator`,
  `classification_metric_report.json`, validation-only threshold sweep, confusion
  matrix, precision/recall/FPR/FNR, PR-oriented ranking metrics, numeric FP/FN cost
  weights, offer-budget gate, no-test-peeking boundary, warning
  `tiny_metric_sample_expected` и 17 behavioral tests.
- Урок `15/04` «Предобработка как часть модели» завершен: shared tiny profile дополнен
  `ml_raw_features.csv` и `preprocessing_contract.json`, CLI
  `preprocessing-contract-checker`, `preprocessing_report.json`,
  `preprocessing_state.json`, `preprocessed_feature_matrix.csv`, train-only fitted
  imputation/scaling/one-hot state, stable transformed feature schema, explicit
  missing-value policy, unknown-category bucket audit, no-fit-before-split boundary,
  warnings `unknown_categories_bucketed` и `tiny_preprocessing_sample_expected` и 18
  behavioral tests.
- Урок `15/05` «scikit-learn Pipeline» завершен: добавлена runtime-зависимость
  `scikit-learn==1.9.0`, shared tiny profile дополнен `pipeline_spec.json`, CLI
  `pipeline-runner`, `pipeline_report.json`, `pipeline_predictions.csv`,
  `pipeline_serialized_spec.json`, единый `Pipeline` с `ContractPreprocessor` и
  `LogisticRegression`, train-only `Pipeline.fit`, validation/test `predict_proba`,
  serialized fit trace, no-external-preprocessed-matrix boundary, warnings
  `pipeline_unknown_categories_bucketed` и `tiny_pipeline_training_sample_expected` и
  20 behavioral tests.
- Урок `15/06` «ColumnTransformer» завершен: shared tiny profile дополнен
  `column_transformer_spec.json` и binary feature `had_support_ticket_14d`, CLI
  `column-transformer-auditor`, `column_transformer_report.json`,
  `column_transformer_routing.csv`, `column_transformer_feature_schema.csv`,
  `column_transformer_predictions.csv`, `column_transformer_serialized_spec.json`,
  sklearn `Pipeline(ColumnTransformer, LogisticRegression)` с explicit
  numeric/categorical/binary routes, `remainder=drop`, `get_feature_names_out`,
  unknown-category bucket before `OneHotEncoder`, no-silent-dropped-columns boundary,
  warnings `column_transformer_unknown_categories_bucketed` и
  `tiny_column_transformer_training_sample_expected` и 20 behavioral tests.
- Урок `15/07` «Линейные baseline» завершен: shared tiny profile дополнен
  `linear_baseline_spec.json`, CLI `linear-baseline-trainer`,
  `baseline_report.json`, `baseline_comparison.csv`, `coefficient_table.csv`,
  `baseline_predictions.csv`, `linear_baseline_serialized_spec.json`, dummy и
  regularized logistic sklearn `Pipeline(ColumnTransformer, estimator)`, validation-only
  model selection, intercept/regularization trace, coefficient table joined to
  transformed feature schema, warnings `linear_baseline_unknown_categories_bucketed`,
  `tiny_linear_baseline_training_sample_expected` и
  `linear_baseline_does_not_beat_dummy_on_tiny_validation` и 17 behavioral tests.
- Урок `15/08` «Деревья решений» завершен: shared tiny profile дополнен
  `tree_diagnostic_spec.json`, CLI `tree-diagnostic-trainer`, `tree_report.json`,
  `tree_overfit_report.csv`, `tree_node_report.csv`, `tree_rules.txt`,
  `tree_predictions.csv`, `tree_serialized_spec.json`, depth-limited sklearn
  `Pipeline(ColumnTransformer, DecisionTreeClassifier)`, upstream linear-baseline
  handoff gate, train-validation overfit report, readable rule export через transformed
  feature names, warnings `tree_unknown_categories_bucketed`,
  `tiny_tree_training_sample_expected`, `tree_train_validation_gap_exceeds_threshold` и
  `tree_diagnostic_worse_than_selected_baseline_on_validation` и 17 behavioral tests.
- Урок `15/09` «Ансамбли деревьев» завершен: shared tiny profile дополнен
  `tree_ensemble_spec.json`, CLI `tree-ensemble-comparator`, `ensemble_report.json`,
  `ensemble_comparison.csv`, `ensemble_stability_report.csv`,
  `ensemble_feature_importance.csv`, `ensemble_slice_metrics.csv`,
  `ensemble_predictions.csv`, `ensemble_serialized_spec.json`, sklearn
  `Pipeline(ColumnTransformer, RandomForestClassifier)`, upstream tree-diagnostic
  handoff gate, validation-only comparison dummy/logistic/tree/ensemble, seed stability
  across `0/7/13`, MDI/permutation feature-importance audit, validation slice metrics,
  warnings `ensemble_unknown_categories_bucketed`, `tiny_ensemble_training_sample_expected`,
  `ensemble_feature_importance_requires_caution` и `ensemble_slice_metrics_have_small_n`
  и 18 behavioral tests.
- Урок `15/10` «Cross-validation» завершен: shared tiny profile дополнен
  `cv_plan_spec.json` и `ml_cv_fold_manifest.csv`, CLI `cross-validation-planner`,
  `cv_report.json`, `cv_fold_manifest.csv`, `cv_score_report.csv`,
  `cv_predictions.csv`, `cv_no_peeking_audit.csv`, `cv_serialized_spec.json`,
  predeclared group/time-aware folds, no-test-peeking audit, scoring alignment,
  upstream tree-ensemble handoff gate, fold-level score report, validation-only
  predictions, serialized fit trace, warnings `tiny_cv_fold_count_expected` и
  `tiny_cv_validation_sample_expected` и 13 behavioral tests.
- Урок `15/11` «Несбалансированные классы» завершен: shared tiny profile дополнен
  `imbalance_policy_spec.json`, CLI `imbalance-policy-evaluator`,
  `imbalance_report.json`, `class_distribution.csv`, `baseline_trap_report.csv`,
  `imbalance_threshold_report.csv`, `imbalance_predictions.csv`,
  `imbalance_policy_audit.csv`, `imbalance_serialized_spec.json`, class distribution
  по split/CV roles, always-negative accuracy trap, `class_weight="balanced"`
  candidate, validation-only selection, top-k vs fixed-threshold budget diagnostics,
  warnings `imbalance_positive_rate_below_threshold`, `accuracy_trap_detected_on_test`,
  `class_weight_improves_validation_not_test_expected` и
  `fixed_threshold_can_exceed_offer_budget` и 16 behavioral tests.
- Урок `15/12` «Калибровка вероятностей» завершен: shared tiny profile дополнен
  `calibration_policy_spec.json`, CLI `probability-calibration-auditor`,
  `calibration_report.json`, `calibration_bins.csv`, `calibration_metrics.csv`,
  `calibrated_predictions.csv`, `calibration_threshold_impact.csv`,
  `calibration_policy_audit.csv`, `calibration_serialized_spec.json`,
  validation-only smoothed bin-map calibrator, Brier/log loss/ECE comparison,
  calibrated vs uncalibrated top-k/fixed-threshold impact, no-test-calibration
  boundary, warnings `calibration_sample_below_minimum`,
  `calibration_bins_below_min_rows`, `calibration_bins_missing_class_coverage`,
  `fixed_threshold_action_count_changes_after_calibration` и
  `tiny_test_improvement_is_not_production_claim` и 13 behavioral tests.
- Урок `15/13` «Data leakage» завершен: shared tiny profile дополнен
  `leakage_policy_spec.json`, `ml_feature_availability.csv`,
  `ml_feature_selection_log.csv`, `ml_model_selection_log.csv`, CLI
  `ml-leakage-auditor`, `leakage_report.json`,
  `feature_availability_report.csv`, `forbidden_feature_report.csv`,
  `preprocessing_scope_audit.csv`, `feature_selection_audit.csv`,
  `model_selection_audit.csv`, `leakage_policy_audit.csv`,
  `leakage_serialized_spec.json`, upstream calibration handoff gate,
  feature-availability report, forbidden-source table, train-only preprocessing
  audit, feature-selection outside-CV gate, validation-only model-selection gate,
  warnings для видимых rejected forbidden candidates, feature-selection bad patterns
  и test cherry-pick candidates и 16 behavioral tests.
- Урок `15/14` «Анализ ошибок по сегментам» завершен: shared tiny profile дополнен
  `error_analysis_policy_spec.json`, CLI `segment-error-analyzer`,
  `error_analysis_report.json`, `confusion_rows.csv`, `slice_metrics.csv`,
  `small_n_warnings.csv`, `hidden_failure_slices.csv`, `error_examples.csv`,
  `error_analysis_policy_audit.csv`, `error_analysis_serialized_spec.json`,
  test-only calibrated confusion ledger, slice metrics по `segment_id`, `platform`,
  `country`, business cohorts и score bands, small-n warnings, hidden aggregate
  failure candidates (`android`, `organic`, `trial_basic:RU`, `low`) и 15 behavioral
  tests.
- Урок `15/15` «Model card и ограничения» завершен: shared tiny profile дополнен
  `ml_baseline_package_spec.json`, CLI `ml-baseline-packager`,
  `ml_baseline_package.json`, `ml_baseline_package_report.json`, `model_card.md`,
  `decision_report.md`, `evidence_matrix.csv`, `risk_register.csv`,
  `model_card_policy_audit.csv`, `ml_baseline_package_manifest.json`, 14-row upstream
  evidence matrix, 8-row risk register, sha256 manifest для 29 inputs и 7 generated
  outputs, explicit no-production/no-causal-claim decision status
  `review_required_before_production` и 13 behavioral tests.
- Урок `14/01` «Временной индекс, частота и календарный grain» завершен: общий
  deterministic tiny profile, `forecast_scenario.json`, calendar/revision contract,
  CLI-аудитор time index/frequency/calendar coverage, warnings для incomplete rows и
  revisions after origin и 10 behavioral tests.
- Урок `14/02` «Resampling и агрегация» завершен: `subscription_events.csv`,
  `resampling_spec.json`, CLI `resampling-pipeline`, daily/weekly stock-from-deltas
  aggregation, UTC-to-business-date normalization, reconciliation с published
  `metric_observations.csv`, partial-period warnings и 11 behavioral tests.
- Урок `14/03` «Rolling и expanding windows» завершен: `window_feature_spec.json`, CLI
  `window-feature-builder`, leakage-safe lag/rolling/expanding features, `window_features.csv`,
  `leakage_audit.csv`, warmup/partial row policy и 12 behavioral tests.
- Урок `14/04` «Тренд, сезонность и календарные эффекты» завершен:
  `seasonality_profile_spec.json`, CLI `seasonality-profiler`, `trend_summary.csv`,
  `seasonality_profile.csv`, `calendar_effect_inventory.csv`, known-before-origin gates
  для holiday/campaign/release context, warnings для partial rows, future campaign без
  historical examples и single-month profile, 13 behavioral tests.
- Урок `14/05` «Временная утечка» завершен: `temporal_leakage_spec.json`, CLI
  `temporal-leakage-auditor`, `cutoff_contract.json`, `forbidden_feature_report.csv`,
  `temporal_leakage_report.json`, gates для time-ordered cutoff, embargo rows,
  selected feature availability, known-before-origin calendar features, past-only window
  audit и revision policy, warnings для отклоненных forbidden candidates и excluded
  revisions after origin, 14 behavioral tests.
- Урок `14/06` «Наивные и сезонные baseline» завершен: `baseline_forecast_spec.json`,
  CLI `baseline-forecaster`, `baseline_forecasts.csv`, `baseline_trace.csv`,
  `baseline_report.json`, naive/seasonal naive/drift/moving-average forecasts,
  seasonal-naive primary baseline policy, forecast trace anchors, warnings для known
  future campaign context и embargo gap, 15 behavioral tests.
- Урок `14/07` «Декомпозиция ряда» завершен: `decomposition_spec.json`, CLI
  `stl-decomposition-reporter`, `decomposition_components.csv`,
  `residual_diagnostics.csv`, `decomposition_report.json`, STL additive components,
  reconstruction invariant, residual diagnostics, diagnostic-only interpretation policy,
  warning для short history и 15 behavioral tests.
- Урок `14/08` «ETS и ARIMA» завершен: `statsmodels_model_spec.json`, CLI
  `statsmodels-forecast-runner`, `candidate_forecasts.csv`, `model_diagnostics.csv`,
  `library_vs_baseline.csv`, `model_report.json`, predeclared ETS/ARIMA candidates,
  convergence/warning diagnostics, shape-only comparison к `seasonal_naive_7`,
  warnings для short history, known future calendar effects и embargo gap, 15
  behavioral tests.
- Урок `14/09` «Rolling backtesting» завершен: `backtesting_spec.json`,
  `backtest_observations.csv`, CLI `rolling-origin-backtester`,
  `split_manifest.csv`, `backtest_forecasts.csv`, `backtest_errors.csv`,
  `backtest_report.json`, expanding и rolling origins, fixed 3-day horizon,
  gap/embargo checks, refit_each_origin policy, raw error table без premature
  leaderboard, warnings для small origin count и shorter-than-final horizon, 14
  behavioral tests.
- Урок `14/10` «Метрики прогноза» завершен: `forecast_metric_spec.json`, CLI
  `forecast-metric-evaluator`, `forecast_metrics.csv`,
  `metric_suitability_audit.csv`, `mase_denominators.csv`,
  `metric_leaderboard.csv`, `metric_report.json`, MAE/RMSE/MAPE/sMAPE/WAPE/MASE,
  overall/segment/horizon slices, weighted-MASE leaderboard policy,
  zero-denominator handling для MAPE/sMAPE и 14 behavioral tests.
- Урок `14/11` «Интервалы прогноза» завершен: `prediction_interval_spec.json`, CLI
  `prediction-interval-calibrator`, `interval_forecasts.csv`,
  `interval_backtest_predictions.csv`, `interval_coverage.csv`,
  `interval_calibration_audit.csv`, `interval_report.json`,
  residual/bootstrap/model-based prediction intervals, empirical coverage по
  rolling-origin backtests, uncertainty statements, horizon extrapolation warnings и
  15 behavioral tests.
- Урок `14/12` «Аномалии временных рядов и forecast package» завершен:
  `forecast_package_spec.json`, CLI `time-series-forecast-packager`,
  `anomaly_flags.csv`, `quality_gate_summary.csv`, `anomaly_policy.json`,
  `forecast_package_report.json`, `decision_report.md`,
  `forecast_package_manifest.json`, anomaly triage labels
  `data_quality`/`calendar_expected`/`model_misspecification`/`inconclusive`,
  upstream warning propagation, no-causal-claim boundary, checksum manifest и
  13 behavioral tests.
- Урок `13/01` «Причинный вопрос и estimand» завершен: target trial-style contract,
  ATE/ATT/LATE semantics, общий causal dataset и CLI-валидатор question/estimand/timing.
- Урок `13/02` «Причинные DAG и идентификация» завершен: machine-readable causal DAG,
  identification map, ручные d-separation/backdoor checks, association-vs-intervention
  audit, запрет bad controls и CLI-валидатор DAG/identification с 17 behavioral tests.
- Урок `13/03` «Confounders и backdoor adjustment» завершен: confounder inventory,
  measured/unmeasured report, candidate adjustment-set spec, backdoor path audit,
  observed baseline primary recommendation, claim policy при remaining unmeasured
  confounding и CLI-аудитор с 15 behavioral tests.
- Урок `13/04` «Colliders, mediators и selection bias» завершен: bad-control policy,
  candidate control actions, mediator/collider/selection mechanism examples,
  population-change gate для post-treatment filters, outcome leakage checks, allowed
  baseline handoff для будущих estimators и CLI-аудитор с 16 behavioral tests.
- Урок `13/05` «Regression adjustment и g-formula» завершен: g-formula spec,
  outcome-regression g-computation estimator, ручная OLS standardization,
  statsmodels cross-check, standardized potential outcomes, ATE/ATT estimates,
  LPM bounds/support diagnostics, bad-control/source coverage gates и CLI с 16
  behavioral tests.
- Урок `13/06` «Matching и баланс ковариат» завершен: matching spec, nearest-neighbor
  ATT matching по pre-treatment covariates, standardized Euclidean distance, caliper,
  replacement policy, common-support audit, matched pairs, balance table, love plot data,
  bad-control/source coverage gates и CLI с 16 behavioral tests.
- Урок `13/07` «Propensity weighting и doubly robust оценка» завершен: ridge propensity
  scoring, stabilized IPW, Horvitz-Thompson и Hájek estimates, AIPW residual correction,
  overlap/tail diagnostics, weight и effective-sample-size report, trimming sensitivity,
  stress tests для misspecified treatment/outcome models, bad-control/source coverage
  gates и CLI с 19 behavioral tests.
- Урок `13/08` «Difference-in-Differences» завершен: региональный rollout DiD spec,
  manual 2x2 north-vs-south not-yet-treated estimate, saturated regression
  reconciliation, pretrend slope check, fake pre-period и composition placebo checks,
  event-study table, sparse-tail warning, full-panel TWFE diagnostic-only warning для
  staggered adoption и CLI с 17 behavioral tests.
- Урок `13/09` «RDD и instrumental variables: дизайн до оценки» завершен:
  quasi-experiment spec, fuzzy RDD around friction-score cutoff, local bandwidth,
  density/manipulation и continuity checks, sharp-vs-fuzzy candidate policy, IV first
  stage, reduced form, Wald LATE, observed balance screen, LATE-not-ATE claim policy,
  warnings по diagnostic-only tiny RDD и непроверяемым exclusion/monotonicity assumptions
  и CLI с 16 behavioral tests.
- Урок `13/10` «Sensitivity analysis и falsification checks» завершен:
  sensitivity spec, refutation suite, placebo treatment/outcome checks,
  negative-control outcome, upstream DiD placebo propagation, omitted-confounding
  sensitivity grid, cross-design estimate comparison, no-pooling policy для разных
  estimands и claim policy, которая блокирует single strong causal effect statement,
  с CLI и 15 behavioral tests.
- Урок `13/11` «Causal workflow и границы автоматизации» завершен:
  causal workflow spec, causal-study-package builder, интеграция 15 upstream artifacts
  фазы 13, DoWhy-compatible trace `model -> identify -> estimate -> refute`, EconML
  scope audit, checksum manifest, no-pooling policy для разных estimands и финальная
  claim policy, которая блокирует single strong causal claim, с CLI и 14 behavioral
  tests.
- Фаза 18 спроектирована как stage-gated capstone на 44 часа: route brief, data contract,
  baseline, implementation, independent verification, peer review и defense; завершены
  `18/01`–`18/06`.
- Следующий содержательный этап — разработка урока `18/07` «Защита решения».
- Полный маршрут: 237–324 часа.
- Сайт содержит главную дорожную карту, каталог, маршруты, глоссарий и локальный прогресс.

Готовность по фазам: `00` — 4/4, `01` — 7/7, `02` — 9/9, `03` — 11/11,
`04` — 12/12, `05` — 11/11, `06` — 11/11, `07` — 10/10, `08` — 11/11,
`09` — 10/10, `10` — 11/11, `11` — 11/11, `12` — 11/11, `13` — 11/11,
`14` — 12/12, `15` — 15/15, `16` — 11/11, `17` — 12/12, `18` — 6/7.

## Историческая запись о ранней разработке фаз 00–02

Ниже сохранена нумерация уроков на момент соответствующих коммитов. Текущая нумерация
начала курса зафиксирована в верхнем разделе этого файла и в `curriculum.json`.

После коммита `83ee574` разработаны уроки `01/02`–`01/09`.

- `01/02`: урок заново выстроен как прямое продолжение `revenue-project` из `01/01`:
  declaration, locking, syncing, строгий запуск, удаление и восстановление `.venv`;
  большой самописный `uv_project_check.py` заменён небольшим контрольным расчётом,
  потому что состояние lock-файла и окружения проверяют штатные команды `uv`;
- `01/03`: metadata, runtime/dev dependencies, `[tool.*]`, console scripts и CLI
  `pyproject_audit.py`;
- `01/04`: Jupyter architecture, kernelspec, runtime evidence и CLI
  `kernel_diagnostic.py`;
- `01/05`: clean notebook policy, top-down execution и CLI `notebook_audit.py`;
- `01/06`: importable package, data contract, `Decimal` и JSON CLI;
- `01/07`: явная Ruff policy, safe fixes и lint/format quality gate;
- `01/08`: behavioral pytest suite, boundaries, fixtures и parametrization;
- `01/09`: standalone GitHub Actions project, locked sync и workflow self-audit;
- все уроки содержат поведенческие тесты и развивающие ссылки на официальную
  документацию.

Фазы 00 и 01 завершены; в фазе 01 готовы девять из девяти уроков.

Перед фазой 02 добавлен корневой reproducible environment:

- runtime: NumPy 2.4.6;
- development: pytest 9.0.3, Ruff 0.15.17 и PyYAML 6.0.3;
- точные версии зафиксированы в `uv.lock`;
- GitHub Pages CI использует setup-uv 8.2.0, uv 0.11.21 и
  `uv sync --locked --dev`;
- валидатор требует `pyproject.toml` и `uv.lock`, repository test сверяет dependency
  contract и locked CI.

Фаза 02 полностью разработана:

- `02/01`–`02/03`: модель `ndarray`, предсказание форм и аудит `dtype`, диапазонов,
  пропусков и памяти;
- `02/04` завершает выбор данных через индексацию, маски и явное различие copy/view;
- новый `02/05` закрывает структурную подготовку перед вычислениями: `concatenate` по
  существующей оси, `stack` по новой оси, единая устойчивая перестановка связанных
  массивов, обратное восстановление, `unique` с частотами и кодами, первые экстремумы,
  явные политики dtype и `NaN`; аудитор покрыт 18 behavioral tests;
- `02/06` перестроен вокруг предметных осей и grain результата: одна и несколько осей,
  аддитивность, `group_size` / `valid_count` / `missing_count`, явные политики пропусков,
  полностью пустые группы, `keepdims`, минимальный контракт `ddof` и наблюдаемый `dtype`;
  различие `sum`, `cumsum` и `diff` встроено как граница между редукцией, накоплением и
  переходами; артефакт поддерживает именованные и отрицательные оси и покрыт 16 tests;
- `02/07` перестроен как подробный мост от агрегатов к поэлементным операциям:
  координатная модель и ufunc, ориентация одномерного вектора, позиционное и предметное
  согласование осей, связь `keepdims` с broadcasting, отдельный прогноз допустимости
  операции и выходного `dtype`, ограничения in-place записи и оценка памяти;
  артефакт объясняет контракт без выделения результата и покрыт 19 tests;
- `02/08` перестроен вокруг локального `numpy.random.Generator`, различия seed/state/stream,
  предметных осей `size`, явной передачи RNG, бинарной сценарной модели через broadcasting,
  manifest запуска и оценки памяти; sampling distribution сохранен как необязательное
  расширение с явным переходом к фазе 09, основной артефакт покрыт 17 tests;
- `02/09` перестроен как мост от модели массива к осознанной оптимизации: предметная ось
  и доменный контракт, прозрачный Python-baseline, построчная и итоговая equivalence gate,
  calculation-only scope, повторные времена и медианы, оценка временных ndarray и
  ограниченный вывод с environment metadata; основное объяснение явно отделяет ufunc и
  array API от `np.vectorize`, исполняющего Python callback; артефакт покрыт 17 tests;
- `02/10` перестроен как итоговый численный контракт фазы: выбор точного или
  приближенного сравнения, вывод `rtol` и `atol` из единиц и масштаба, обязательный
  shape gate, опциональный dtype gate, явные политики `NaN` и `inf`, integer overflow до
  узкой операции, floating normal/subnormal/overflow/underflow и граница между ошибкой
  хранения и аккумулятора; артефакт возвращает ограниченную диагностику расхождений,
  различает коды CLI `0/1/2` и покрыт 24 tests;
- каждый урок содержит самостоятельный артефакт, квиз и не менее восьми behavioral tests.

Фаза 03 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность уроков — 1005 минут, или 16 часов 45 минут;
- каждый урок содержит документацию, executable example, behavioral tests, квиз и
  самостоятельный артефакт;
- суммарно фаза содержит 114 behavioral tests;
- `03/11` реализует интеграционный проект по сборке и передаче order mart;
- runtime дополнен pandas 3.0.3 с учетом Copy-on-Write и нового string dtype;
- добавлены детерминированные `users`, `orders` и `order_items` с контрактом,
  известными дефектами и checksum-манифестом.

Фаза 04 полностью разработана:

- все 12 уроков получили тип, время, последовательные зависимости, измеримый результат и
  артефакт;
- суммарная длительность фазы — 1050 минут, или 17,5 часа;
- `04/12` назначен интеграционным проектом по сборке проверенных SQL-витрин;
- DuckDB 1.5.3 добавлен в runtime и зафиксирован в `uv.lock`;
- добавлены совместимые `users`, `orders`, `order_items` и `events`;
- committed `tiny` содержит 50 строк, локальный `sample` — 525 005 строк для анализа
  планов запросов;
- все 12 уроков переведены в статус `complete`;
- суммарно фаза содержит 98 behavioral tests;
- `04/01`–`04/05` покрывают grain, SELECT, NULL, агрегаты и безопасные JOIN;
- `04/06`–`04/09` покрывают CTE, окна, временные зоны и cohort matrix;
- `04/10`–`04/11` поставляют Python runner и сравнение `EXPLAIN ANALYZE`;
- `04/12` реализует интеграционную поставку `order_mart.csv`, `user_summary.csv` и
  checksum-manifest с явной границей SQL/Python/pandas.

Фаза 05 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность фазы — 840 минут, или 14 часов;
- каждый урок содержит документацию полного учебного цикла, executable example,
  behavioral tests, квиз и самостоятельный артефакт;
- суммарно фаза содержит 90 behavioral tests;
- `05/01`–`05/03` покрывают CSV, Excel и вложенный JSON через явные контракты;
- `05/04`–`05/07` реализуют безопасный HTTP download, pagination/retries, HTML parsing и
  параметризованный SQLAlchemy Core reader;
- `05/08`–`05/10` поставляют typed Parquet converter, Arrow compatibility report и
  partitioned dataset builder с анализом fragment pruning и small files;
- `05/11` собирает интеграционный resilient loader с raw cache, SHA-256, immutable
  versioned datasets и атомарным указателем `current.json`;
- добавлены 14 детерминированных fixtures и шесть машинных контрактов для CSV, Excel,
  JSON, HTML, SQL и Parquet;
- runtime дополнен openpyxl 3.1.5, Requests 2.34.2, Beautiful Soup 4.15.0,
  SQLAlchemy 2.0.50 и PyArrow 24.0.0;
- ограничение pandas roundtrip, который не сохраняет Arrow field-level
  `nullable=False`, явно зафиксировано в compatibility report;
- глубокая Arrow memory model оставлена фазе 12, а оформление Excel-выдачи — фазе 17.

Фаза 06 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность — 930 минут, или 15,5 часа;
- уроки образуют последовательность от visual question brief и аудита данных до
  воспроизводимого EDA-report;
- Matplotlib отвечает за явные Figure/Axes и статический экспорт, Seaborn — за
  статистические сравнения и facets, Plotly — за exploratory drill-down, Altair — за
  проверяемую декларативную спецификацию;
- общий датасет `user_journeys` имеет grain «один пользователь и одно семидневное окно»
  и profiles `tiny` и `sample`;
- в данные заложены неполные окна наблюдения, дубликат, структурные пропуски,
  heavy tails, composition effect, Android regression и группы разного размера;
- `06/11` назначен интеграционным проектом: report.md, static figures, interactive
  appendix, Vega-Lite specs и checksum-manifest;
- границы со статистикой, надежностью, причинным анализом и доставкой закреплены в
  `docs/phase-06-design.md`;
- runtime дополнен Matplotlib 3.11.0, Seaborn 0.13.2, Plotly 6.8.0 и Altair 6.2.1;
- `06/01`–`06/02` поставляют visual question brief и машинный аудит grain, типов,
  missingness, диапазонов, дубликатов и observation windows;
- `06/03`–`06/06` покрывают явные Figure/Axes, histogram и ECDF, стратифицированные
  связи и percentile bootstrap с provenance;
- `06/07`–`06/10` поставляют faceted Seaborn panel, standalone Plotly explorer,
  валидированную Vega-Lite specification и accessibility review checklist;
- `06/11` собирает question, audit, report.md, PNG/SVG, standalone HTML, linked spec,
  visual review и checksum manifest;
- суммарно фаза содержит 91 behavioral test;
- детерминированный `tiny` profile содержит 25 строк и 24 уникальных пользователя,
  локальный `sample` генерирует 20 001 строку с одним дубликатом.

Фаза 07 полностью разработана:

- десять последовательных уроков рассчитаны на 825 минут, или 13,75 часа;
- базовый pytest и GitHub Actions из фазы 01 не повторяются: они применяются к
  многостадийным pipeline и доменным failure classes;
- общий order-quality pipeline использует `users`, `orders` и `order_items`;
- матрица дефектов покрывает grain, null/orphan keys, schema/type drift,
  reconciliation, configuration, regression, freshness, volume и atomic publication;
- runtime дополнен Pandera 0.31.1 и Pydantic 2.13.4, development environment —
  Hypothesis 6.155.2;
- `07/01` реализует CLI `order-invariant-gate`: проверяет ключи, status, currency,
  денежный домен и timezone и сверяет pandas-агрегаты независимым `Decimal`-контролем;
- committed `tiny` содержит 6 users, 10 orders и 12 order items; локальный `sample`
  генерирует 1 000 users и 5 000 orders;
- границы фазы и интеграционный reliable order pipeline зафиксированы в
  `docs/phase-07-design.md`.
- `07/02`–`07/04` поставляют contract-focused stages, фабрику 12 классов дефектов и
  Hypothesis suite для денежных агрегатов и дедупликации;
- `07/05`–`07/07` реализуют версионированный Pandera-контракт, strict Pydantic config и
  восемь независимых DuckDB violation queries;
- `07/08`–`07/09` добавляют reviewed semantic golden, точный JSON-path diff и монитор
  freshness, volume, null и duplicate rates;
- `07/10` собирает immutable version с Parquet/CSV mart, пятью quality reports,
  JSONL telemetry, checksum manifest и атомарным `current.json`;
- суммарно фаза содержит 60 behavioral tests.

Фаза 08 спроектирована:

- 11 последовательных уроков на 12-16 часов ведут от дерева метрик и tracking plan к
  активности, воронкам, когортам, retention, монетизации, сегментации, guardrails,
  аномалиям и финальной рекомендации;
- границы закреплены в `docs/phase-08-design.md`: фаза не подменяет статистический
  вывод, A/B-эксперименты, причинный анализ, production SDK-интеграцию, финансовую LTV
  модель и time-series forecasting;
- единая продуктовая задача использует события, сессии, подписки, заказы, поддержку и
  календарь релизов вымышленного подписочного сервиса;
- финальный артефакт `08/11` — `product-problem-investigation/` с `metric-tree.json`,
  `tracking-plan.json`, `metric-specs.json`, metric tables, anomalies, report,
  recommendation и checksum manifest;
- новых обязательных библиотек не требуется: фаза переиспользует pandas, DuckDB, NumPy,
  Pandera/Pydantic и визуальный стек из фаз 03-07.

Урок `08/01` «Дерево метрик» разработан:

- добавлен общий продуктовый dataset фазы 08 с `users`, `sessions`, `events`,
  `subscriptions`, `orders`, `support_tickets`, `release_calendar`, контрактом и
  воспроизводимым генератором tiny/sample;
- урок строит дерево `activation_rate_7d` с input-метриками
  `onboarding_completion_rate`, `paywall_to_trial_conversion_7d` и guardrails
  `support_ticket_rate_7d`, `subscription_cancel_rate_14d`;
- артефакт `metric-tree-validator` проверяет роли outcome/input/guardrail, связи,
  совпадение tree/specs, denominator, source tables, validation checks и направление
  риска guardrail-метрик;
- lesson suite содержит 9 behavioral tests.

Урок `08/02` «Событийная модель продукта» разработан:

- добавлен machine-readable `tracking_plan.json` для 12 продуктовых событий фазы 08:
  `app_open`, signup, onboarding, activation, paywall, trial, subscription, order и
  support events;
- артефакт `event-model-validator` проверяет обязательные колонки, уникальность
  `event_id`, известные event names и versions, required properties, identity policy,
  timezone-aware timestamps, `received_at >= occurred_at`, late arrivals, mobile
  `app_version` и ссылки `used_by_metrics` на metric specs из `08/01`;
- lesson suite содержит 12 behavioral tests, включая неизвестные события, version drift,
  невалидный `properties_json`, пустой `user_id`, duplicate delivery и late arrival.

Урок `08/03` «Активность и активная аудитория» разработан:

- добавлен `activity_spec.json` с grain `user_id`, meaningful active events, окнами
  1/7 дней, business timezone `Europe/Moscow`, eligible population и исключением test
  users;
- артефакт `active-audience-calculator` строит `activity.csv` с `eligible_users`,
  `active_users`, `activity_rate`, `active_event_count` и флагом `is_complete_window`;
- quality report проверяет activity spec, связь active events с tracking plan,
  обязательные колонки, уникальность `event_id`/`user_id`, identity active events,
  timezone-aware timestamps и наличие activity rows;
- lesson suite содержит 12 behavioral tests: zero-activity days, incomplete rolling
  windows, test-user exclusion, duplicate delivery, missing `user_id`, timezone
  conversion и CLI failure для invalid spec.

Урок `08/04` «Воронки и неоднозначность конверсии» разработан:

- добавлен `funnel_spec.json` с closed funnels для activation и paywall-to-trial,
  unit `user_id`, strict ordering, conversion window 7 дней, business timezone
  `Europe/Moscow` и исключением test users;
- артефакт `funnel-calculator` строит `funnel.csv` с `units`,
  `conversion_from_start`, `conversion_from_previous` и `dropoff_from_previous`;
- калькулятор поддерживает units `user_id`, `session_id`, `user_day`, strict/loose
  ordering, дедупликацию `event_id`, проверку step events через tracking plan и
  late-arrival policy;
- lesson suite содержит 12 behavioral tests: эталонные funnel counts, duplicate
  delivery, unknown step event, unsupported unit, missing `user_id`, strict versus
  loose order, cross-session, cross-day, late arrivals и CLI failure для invalid spec.

Урок `08/05` «Когортный анализ» разработан:

- добавлен `cohort_spec.json` для daily cohort matrix: cohort date из `registered_at`,
  unit `user_id`, age_day 0-7, business timezone `Europe/Moscow`, исключение test users
  и политика `blank_rate` для incomplete windows;
- артефакт `cohort-matrix-calculator` строит `cohorts.csv` с `cohort_size`,
  `active_users`, `activity_rate`, `is_complete_window` и `active_event_count`;
- расчет использует active events из `08/03` `activity_spec.json`, проверяет их связь с
  tracking plan, дедуплицирует `event_id`, фиксирует complete/incomplete windows против
  `observation_end_date` и не маскирует incomplete windows нулями;
- lesson suite содержит 13 behavioral tests: эталонные cohort counts, full grid, zero
  activity cells, blank incomplete rates, test-user exclusion, duplicate delivery,
  missing `user_id`, unknown active event, age-day continuity, timezone conversion,
  observation end override, late arrivals и CLI failure для invalid spec.

Урок `08/06` «Retention и возвращаемость» разработан:

- добавлен `retention_spec.json` для `active_retention`: start source `registered_at`,
  unit `user_id`, return events из `activity_spec`, age_day 1-7, business timezone
  `Europe/Moscow`, исключение test users и политика `blank_rate` для incomplete windows;
- артефакт `retention-calculator` строит `retention.csv` с режимами `exact_day` и
  `on_or_after`, фиксированным `cohort_size`, `retained_users`, `retention_rate`,
  границами return window, `is_complete_window` и `return_event_count`;
- расчет дедуплицирует `event_id`, не считает day 0 activity возвращением, проверяет
  return events против `activity_spec` и tracking plan, фиксирует complete/incomplete
  windows против `observation_end_date` и не маскирует incomplete windows нулями;
- lesson suite содержит 14 behavioral tests: full retention grid, sample CSV parity,
  day-0 exclusion, exact-day versus on-or-after semantics, incomplete on-or-after
  horizon, duplicate delivery, missing `user_id`, unknown return event, age-day
  continuity, unsupported modes, observation end override, timezone conversion, late
  arrivals и CLI failure для invalid spec.

Урок `08/07` «Выручка, ARPU и LTV» разработан:

- добавлен `monetization_spec.json` для `cohort_monetization`: cohort date из
  `registered_at`, unit `user_id`, revenue windows D0/D7, business timezone
  `Europe/Moscow`, исключение test users, явные paid/refunded/pending order statuses,
  subscription lifecycle statuses и политика `blank_metrics` для incomplete windows;
- артефакт `monetization-calculator` строит `monetization.csv` с `gross_revenue_rub`,
  `refund_amount_rub`, `realized_revenue_rub`, `arpu_rub`, `arppu_rub`, `ltv_rub`,
  paid/refunded/pending order counts, subscription starts, cancellations и
  `is_complete_window`;
- расчет считает деньги на grain `order_id`, дедуплицирует `order_id` и
  `subscription_id`, не считает pending orders выручкой, показывает refunded orders как
  gross/refund с нулевой realized revenue, считает subscriptions только как lifecycle
  signals и защищает результат от many-to-many revenue join multiplication;
- lesson suite содержит 15 behavioral tests: эталонные D0 ARPU/LTV, sample CSV parity,
  refund и pending semantics, blank incomplete LTV windows, cancellations only in
  complete windows, duplicate orders/subscriptions, unknown users, currency mismatch,
  negative amount, revenue-window contract, timezone conversion, no join multiplication
  и CLI failure для invalid spec.

Урок `08/08` «Сегментация без самообмана» разработан:

- добавлен `segmentation_spec.json` для `activation_rate_d0_by_segment`: cohort periods
  baseline/comparison, unit `user_id`, activation event `feature_value_seen`, business
  timezone `Europe/Moscow`, исключение test users, predeclared dimensions
  `platform`/`acquisition_channel`, exploratory dimension `country` и
  `minimum_cell_size`;
- артефакт `segmentation-calculator` строит `segments.csv` с overall,
  `segment_metric` и `decomposition` rows, `traffic_share`, `is_reportable`,
  `is_exploratory`, within-segment effect, composition effect и overall delta;
- расчет проверяет dimensions против `users.csv`, activation event против tracking plan,
  primary decomposition dimension против predeclared status, дедуплицирует `event_id`,
  отлавливает missing/unknown `user_id`, late arrivals и запрещает causal claims без
  эксперимента;
- lesson suite содержит 15 behavioral tests: эталонные segment rates, sample CSV parity,
  exploratory flags, minimum cell size, predeclared primary dimension, unknown activation
  event, duplicate delivery, missing/unknown `user_id`, late arrivals, timezone
  conversion, observation end override, causal-claim guard, decomposition sum и CLI
  failure для invalid spec.

Урок `08/09` «Guardrail-метрики» разработан:

- добавлен `guardrail_spec.json` для трех рисков: `support_ticket_rate_7d`,
  `subscription_cancel_rate_14d` и `refund_rate_7d`, с periods baseline/comparison,
  business timezone `Europe/Moscow`, observation end, `risk_direction=up_is_bad`,
  `max_rate`, `max_delta`, complete-window policy и overall decision rules;
- артефакт `guardrail-calculator` строит `guardrails.csv` с metric и assessment rows,
  baseline/comparison values, absolute delta, threshold breach, decision status
  `breached`/`watch`/`ok`/`incomplete` и итоговым `overall_decision`;
- расчет проверяет guardrails против metric specs для уже объявленных guardrail-метрик,
  дедуплицирует tickets/subscriptions/orders, проверяет known users, timezone-aware
  timestamps, lifecycle cancelled subscriptions и refund domain по валюте, статусу и
  неотрицательной сумме;
- lesson suite содержит 15 behavioral tests: threshold breaches, sample CSV parity,
  duplicate tickets/subscriptions/orders, unknown support users, subscription lifecycle,
  refund domain, metric spec role/direction, incomplete windows, watch status,
  timezone conversion, test-user exclusion и CLI failure для invalid spec.

Урок `08/10` «Аномалии продуктовых метрик» разработан:

- добавлен `anomaly_spec.json` с periods baseline/comparison, quality gates для
  freshness, duplicate IDs, late arrivals, required events, event volume и tracking
  completeness, thresholds для guardrail delta, composition effect и release window;
- артефакт `anomaly-detector` строит `anomalies.json` с `quality_gates`,
  `summary.by_classification` и candidates классов `data_quality`, `composition`,
  `calendar_effect`, `product_signal`;
- расчет блокирует `product_signal`, если quality gates не прошли, связывает breached
  guardrails с segment decomposition и release calendar и не формулирует causal claim по
  календарному совпадению;
- lesson suite содержит 13 behavioral tests: эталонные classifications, sample JSON
  parity, duplicate event IDs, unknown event names, missing required events, late
  arrivals, freshness, received-before-occurred, volume gate, thresholds и CLI failure
  для failed gates.

Урок `08/11` «Бизнес-вывод и рекомендация» разработан:

- добавлен `product_problem_builder.py`, который собирает
  `product-problem-investigation/` из артефактов `08/01`–`08/10`: brief, metric tree,
  metric specs, tracking plan, metric tables, anomalies, audits, figures, report,
  recommendation и checksum manifest;
- recommendation выбирает `investigate`, отклоняет автоматический `continue` из-за
  breached guardrails, не выбирает немедленный rollback без causal evidence и фиксирует
  next steps по Android paywall release, support/cancel/refund разбору и будущему
  experiment/holdout;
- builder проверяет decision boundary, cited claims, существование artifact paths,
  разрешение `metric_id`, запрет unsupported causal wording и SHA-256 manifest;
- lesson suite содержит 14 behavioral tests: delivery files, manifest verification,
  sample package parity, machine-readable recommendation, evidence-map checks,
  causal-claim guard, uncited/unknown/invalid decision failures, event/metric audits,
  byte-identical metric copies, PNG figures, CLI и missing source failure.

Фаза 09 полностью разработана:

- 10 последовательных уроков рассчитаны на 825 минут, или 13,75 часа;
- границы закреплены в `docs/phase-09-design.md`: фаза систематизирует sampling
  assumptions, uncertainty, confidence intervals, bootstrap, correlation, regression
  inference, diagnostics и robust sensitivity checks;
- фаза самостоятельна для product и ML-маршрутов и не зависит от артефактов фазы 08;
- единая статистическая задача использует user-level extract подписочного сервиса:
  `population_users`, `sampling_frame`, `sample_observations`, `segment_reference`;
- итоговый артефакт `09/10` — `statistical-evidence-report/` с sampling audit,
  distribution cards, point estimates, bias/variance, intervals, bootstrap, correlation
  audit, OLS diagnostics, robust checks, report и checksum manifest;
- SciPy добавлен в `09/02` и зафиксирован в locked runtime как 1.17.1; statsmodels
  добавлен в `09/08` и зафиксирован как 0.14.6 вместе с `patsy`.

Урок `09/01` «Популяция, выборка и механизм отбора» разработан:

- добавлен общий dataset фазы 09 с таблицами `population_users`, `sampling_frame`,
  `sample_observations`, `segment_reference`, контрактом и детерминированным генератором
  tiny/sample;
- tiny profile содержит 8 eligible non-test users и одного test user; sampling frame
  пропускает `U006`, создавая undercoverage для low-end Android, а sample содержит
  segment-level non-response без структурной поломки;
- артефакт `sampling-frame-auditor` проверяет required spec fields, sampling unit,
  ключи, связи population/frame/sample, probability domain, inverse-probability weights,
  complete observation windows, segment coverage, segment response и unequal inclusion
  probabilities;
- report разделяет blocking errors и warning-level estimation risks: warning-и не ломают
  CLI, но должны идти в limitations будущих estimators и intervals;
- lesson suite содержит 10 behavioral tests: structural-valid/warning baseline,
  segment response warning, manual missing frame user, duplicate sample grain, unknown
  sample user, incomplete window, invalid probability/weight, unsupported sampling unit,
  CLI output и blocking-error exit code.

Урок `09/02` «Распределения как модели» разработан:

- добавлен SciPy в locked runtime (`scipy==1.17.1`) и repository dependency contract;
- артефакт `distribution-card-builder` строит карточки распределений для
  `activation_7d`, `first_order_amount_rub_positive`, `support_tickets_7d` и
  `onboarding_seconds`;
- карточки фиксируют family, SciPy API, support, observed `n`, параметры, empirical
  summaries, checks, assumptions, failure modes и limitations;
- revenue нули сохраняются как отдельная mass перед lognormal positive fit, а
  `onboarding_seconds=0` блокируется как нарушение support `x > 0`;
- Poisson count card проверяет non-negative integer support и mean/variance dispersion;
- lesson suite содержит 13 behavioral tests: model coverage, ручной Bernoulli parameter,
  positive-revenue lognormal fit, Poisson diagnostics, onboarding right-tail warning,
  committed cards parity, invalid boolean, negative revenue, fractional count, zero
  duration, unknown metric column, CLI success/failure и example output.

Урок `09/03` «Оценки и свойства оценок» разработан:

- добавлен артефакт `estimator-runner`, который читает `sample_observations.csv`,
  `estimator_spec.json`, upstream sampling audit из `09/01` и distribution cards из
  `09/02`;
- runner выпускает `point_estimates.csv` и `estimator_report.json` для пяти оценок:
  naive activation proportion, weighted activation proportion, weighted first-order
  revenue mean, onboarding median и weighted support-ticket rate;
- estimator spec явно разделяет parameter, statistic, estimator и estimate, задает
  weight column, distribution-card reference, standard-error method и limitations;
- sampling audit warning ids (`frame_segment_coverage`, `sample_segment_response`,
  `unequal_inclusion_probabilities_declared`) переносятся в limitations каждого estimate;
- quantile standard error сознательно отложен до bootstrap, а weighted estimates показывают
  `sum_weights` и approximate effective sample size;
- lesson suite содержит 17 behavioral tests: baseline estimates, parameter/statistic/
  estimator contract, ручные activation controls, weighted revenue/rate, quantile SE
  deferral, committed CSV/JSON parity, missing card/column, zero weight, unknown
  estimator, invalid sampling audit, CLI success/failure и example output.

Уроки `09/04`–`09/10` разработаны:

- `09/04` добавляет `bias-variance-simulator`: repeated-sampling simulation для полной
  eligible population, coverage-biased frame и unequal frame с non-response; report
  фиксирует bias, variance, MSE и показывает, что маленькая variance может быть
  стабильно неверной.
- `09/05` добавляет `confidence-interval-calculator`: normal proportion и Student t
  intervals, coverage simulation, warning/blocking assumption checks и явный отказ
  выпускать lower/upper при нарушенном `minimum_n`.
- `09/06` добавляет `bootstrap-interval-builder`: percentile/basic/BCa intervals,
  `resampling_unit=user_id`, paired mode, fixed RNG, degenerate distribution diagnostics
  и bootstrap manifest.
- `09/07` добавляет `correlation-auditor`: Pearson/Spearman, shuffled controls,
  stratified sign reversal, constant-stratum warnings и машинный запрет causal wording.
- `09/08` добавляет `ols-inference-runner`: design matrix из model spec, ручной
  `np.linalg.lstsq`, `statsmodels.OLS`, coefficient table, standard errors, confidence
  intervals и claim type `conditional_association_not_causality`.
- `09/09` добавляет `regression-diagnostics-checker`: residuals, condition number, VIF,
  leverage, Cook distance, skipped formal tests for tiny n, warning flags и PNG diagnostics.
- `09/10` добавляет `robust-evidence-packager`: финальный
  `statistical-evidence-report/` с upstream artifacts, robust estimates,
  Mann-Whitney sensitivity, figures, `report.md` и SHA-256 manifest.
- Новые lesson suites: `09/04` — 12 tests, `09/05` — 11, `09/06` — 11, `09/07` — 9,
  `09/08` — 10, `09/09` — 10, `09/10` — 9.

Фаза 10 полностью разработана:

- 11 последовательных уроков рассчитаны на 945 минут, или 15,75 часа;
- границы закреплены в `docs/phase-10-design.md`: фаза покрывает experiment protocol,
  randomization unit, A/A, SRM, MDE/power, effect estimation, bootstrap, CUPED,
  multiple testing, peeking, heterogeneity и decision protocol;
- фаза переиспользует продуктовые постановки фазы 08 и статистические инструменты фазы
  09, но не уходит в production experimentation platform, Bayesian/bandit designs,
  causal DAG/quasi-experiments или polished delivery;
- единая задача — A/B-тест нового paywall/onboarding hint для Android в вымышленном
  подписочном сервисе с guardrails по support tickets, cancellations и refunds;
- итоговый артефакт `10/11` — `experiment-decision-package/` с protocol, assignment
  audit, A/A/SRM, power plan, primary/guardrail effects, bootstrap/CUPED checks,
  multiple-testing policy, peeking audit, segment report, decision и checksum manifest;
- новых обязательных библиотек не добавлено: фаза использует pandas, DuckDB, NumPy,
  SciPy, statsmodels, Pandera/Pydantic и визуальный стек, уже введенные ранее.

Урок `10/01` «Гипотеза и целевая метрика» разработан:

- добавлен первый experiment extract фазы 10 с таблицами `experiments`,
  `experiment_variants`, `users`, `events`, `orders`, `subscriptions`,
  `support_tickets`, `metric_baselines`, `pre_experiment_metrics`, контрактом и
  tiny-manifest;
- урок фиксирует pre-registered protocol для A/B-теста Android paywall/onboarding hint:
  variants, eligible population, primary metric `activation_rate_7d`, guardrails
  `support_ticket_rate_7d`, `subscription_cancel_rate_14d`, `refund_rate_7d`,
  secondary metrics, metric windows, alpha/power/MDE, policies и decision rule;
- артефакт `experiment-protocol-validator` проверяет required fields, variants и traffic
  allocation, timeline, design parameters, eligible population, metric roles, metric
  windows, source tables, guardrail risk directions, CUPED covariates и связь decision
  rule с primary/guardrails;
- lesson suite содержит 13 behavioral tests.

Урок `10/02` «Единица рандомизации» разработан:

- добавлены `randomization_spec.json`, deterministic `assignment_engine.py`,
  assignment/exposure fixtures и расширенный tiny experiment extract с `device_id` и
  `household_id` для interference checks;
- engine строит stable hash buckets по `salt:experiment_id:assignment_unit_id`,
  назначает eligible Android non-test users в control/treatment и формирует exposure
  records из первого `paywall_viewed`;
- audit проверяет randomization spec против protocol, one-unit-one-variant, exact
  eligibility match, stable bucket/variant, balance tolerance, unique exposure IDs,
  exposure timing, assignment/exposure variant consistency и shared interference units;
- lesson suite содержит 14 behavioral tests.

Урок `10/03` «A/A-тест и Sample Ratio Mismatch» разработан:

- добавлены `randomization_health_spec.json`, `randomization_health.py` и committed
  `randomization_health_report.json`;
- diagnostic читает assignments/exposures из `10/02`, pre-treatment metrics и protocol,
  проверяет assignment SRM, exposure SRM, telemetry loss, completeness pre-period metrics,
  standardized covariate balance и exact permutation A/A pseudo-outcomes;
- blocking failures отделены от warning diagnostics: baseline tiny готов к A/B-анализу
  по SRM/telemetry, но честно показывает warning по covariate balance на пяти users;
- lesson suite содержит 12 behavioral tests.

Урок `10/04` «MDE, мощность и размер выборки» разработан:

- добавлены `power_spec.json`, `power_planner.py`, committed `power_plan.json`,
  `mde_grid.csv` и `power_curve.png`;
- planner проверяет upstream `randomization_health_report.json`, затем считает sample
  size для primary proportion `activation_rate_7d` через `NormalIndPower` и для mean
  metric `realized_revenue_per_user_7d` через `TTestIndPower`;
- baseline `0.30`, MDE `+0.03`, alpha `0.05`, power `0.8` дают `2964` users per
  variant для primary metric; planned `12000` per variant дает power `0.999609`;
- MDE grid показывает trade-off для `+1`–`+5` п.п., а simulation sanity check сверяет
  required sample с target power;
- lesson suite содержит 9 behavioral tests.

Урок `10/05` «Сравнение средних и долей» разработан:

- добавлены `effect_spec.json`, `experiment_effect_calculator.py`, committed
  `metric_observations.csv`, `effect_results.csv` и `assumption_checks.json`;
- calculator использует protocol, metric specs, randomization health report и power plan
  из `10/01`–`10/04`, строит user-level observations для primary, guardrails и
  secondary metrics от exposure window;
- effects считаются как absolute/relative lift, confidence interval и p-value:
  proportions через two-sample z-test и Newcombe CI, mean revenue через Welch t-test,
  `refund_rate_7d` как ratio-of-sums;
- primary `activation_rate_7d` в tiny имеет lift `-0.666667` и статус
  `missed_primary_direction`, secondary trial signal остается `diagnostic_only`, а
  guardrails получают `watch`, если harmful delta не исключен interval-ом;
- assumption report сохраняет warnings по tiny sample против power plan,
  normal approximation cell counts и mean variance, поэтому artifact valid, но
  `ready_for_decision = false`;
- lesson suite содержит 9 behavioral tests.

Урок `10/06` «Bootstrap в экспериментах» разработан:

- добавлены `bootstrap_spec.json`, `experiment_bootstrap_analyzer.py`, committed
  `bootstrap_intervals.json`, `bootstrap_distribution.csv` и
  `resampling_manifest.json`;
- analyzer переиспользует `metric_observations.csv`, `effect_results.csv` и
  `assumption_checks.json` из `10/05`, не пересчитывая raw experiment metrics;
- bootstrap resampling идет по `user_id` внутри variants с fixed RNG, а permutation
  sensitivity перемешивает labels при фиксированных group sizes;
- для `refund_rate_7d` сохраняется paired numerator/denominator handling:
  tiny дает `148` invalid bootstrap resamples из `500`, `352` valid resamples и warning
  `paired_denominator_contains_zero_units`;
- primary `activation_rate_7d` получает bootstrap CI `[-1.0, 0.0]` и permutation
  p-value `0.401198`; secondary trial/revenue signals остаются sensitivity layer, а не
  decision;
- manifest фиксирует SciPy `1.17.1`, seeds, resampling unit, число resamples и ratio
  metrics с paired denominator;
- lesson suite содержит 9 behavioral tests.

Урок `10/07` «Снижение дисперсии и CUPED» разработан:

- добавлены `cuped_spec.json`, `experiment_cuped_adjuster.py`, committed
  `cuped_effects.csv`, `adjusted_observations.csv`, `variance_reduction_report.json` и
  `cuped_manifest.json`;
- adjuster переиспользует `metric_observations.csv`, `effect_results.csv` и
  `assumption_checks.json` из `10/05`, а pre-treatment ковариаты берет из
  `pre_experiment_metrics.csv` и сверяет с protocol `cuped_policy`;
- CUPED применяется к user-level primary, support guardrail, secondary trial conversion
  и revenue metrics через `Y - theta * (X - mean(X))`;
- primary `activation_rate_7d` использует `sessions_7d_pre`: raw lift `-0.666667`,
  adjusted lift `-0.416667`, `theta = -0.1`, `correlation = -0.288675`,
  `variance_reduction = 0.083333`;
- `refund_rate_7d` и `subscription_cancel_rate_14d` explicitly skipped: ratio metric
  требует paired numerator/denominator augmentation, а subscription denominator в tiny
  sparse;
- diagnostics блокируют post-treatment covariate, не объявленную в protocol ковариату,
  missing pre-metrics и invalid upstream effect analysis; tiny sample оставляет все
  analyzed metrics в warning status;
- lesson suite содержит 10 behavioral tests.

Урок `10/08` «Множественные проверки» разработан:

- добавлены `multiple_testing_policy.json`, `multiple_testing_policy_checker.py`,
  committed `multiple_testing_report.json`, `adjusted_results.csv` и
  `multiple_testing_manifest.json`;
- checker переиспользует protocol, `effect_results.csv`, bootstrap report,
  CUPED variance report, CUPED effects и assumption checks из уроков `10/01`–`10/07`,
  не пересчитывая experiment metrics в multiple-testing layer;
- policy объявляет primary, guardrail, secondary и exploratory families: primary
  проверяется без поправки, guardrails используют Holm/FWER, secondary и exploratory
  используют FDR/BH;
- ручные Bonferroni, Holm и FDR/BH поправки сверяются со `statsmodels.multipletests` и
  `scipy.stats.false_discovery_control`;
- primary `activation_rate_7d` остается failed: raw p-value `0.931981`, CUPED
  sensitivity p-value `0.804109`, practical status `missed_primary_direction`;
- secondary `paywall_to_trial_conversion_7d` получает adjusted p-value `0.025348`, но
  gate status `blocked_by_primary`, поэтому не может открыть launch decision;
- exploratory сегменты `activation_rate_7d_by_acquisition_channel_paid_search` и
  `activation_rate_7d_by_country_ru` получают adjusted p-values `0.021` и `0.008`, но
  остаются `not_pre_registered_launch_gate`, а country segment помечен как post-hoc;
- итоговый report valid, но `ready_for_decision = false`,
  `launch_allowed_by_multiple_testing = false`;
- lesson suite содержит 12 behavioral tests.

Урок `10/09` «Подглядывание и последовательный анализ» разработан:

- добавлены `peeking_policy.json`, `peeking_audit.py`, committed
  `sequential_monitoring_report.json`, `monitoring_schedule.csv`,
  `peeking_simulation.csv` и `peeking_manifest.json`;
- audit переиспользует protocol из `10/01`, power plan из `10/04` и
  multiple-testing report из `10/08`, не пересчитывая experiment metrics;
- peeking policy разделяет daily quality monitoring (`daily_sample_size`, `daily_srm`,
  `telemetry_loss`) и planned decision looks `interim_50`/`final`;
- O'Brien-Fleming-style Lan-DeMets alpha spending дает boundary `0.005575` на
  information fraction `0.5` и `0.05` на final look;
- observed `interim_50` имеет p-value `0.031`: он пересекает naive `0.05`, но не
  sequential boundary, поэтому status `continue_collecting`;
- два observed looks (`day_05_slack_peek`, `day_10_dashboard_refresh`) помечены как
  `unplanned_decision_peek` и блокируют decision-readiness;
- null simulation показывает false positive inflation: при пяти naive looks
  `naive_false_positive_rate = 0.14155`, O'Brien-Fleming spending дает `0.05955`;
- итоговый report valid, но `ready_for_decision = false` из-за unplanned decision looks
  и upstream multiple-testing launch block;
- lesson suite содержит 11 behavioral tests.

Урок `10/10` «Сегменты и неоднородные эффекты» разработан:

- добавлены `segment_policy.json`, `segment_effect_auditor.py`, committed
  `heterogeneity_report.json`, `segment_effects.csv`, `interaction_checks.csv` и
  `segment_manifest.json`;
- auditor переиспользует protocol, `metric_observations.csv`, users, multiple-testing
  report и peeking report, не пересчитывая upstream experiment metrics;
- predeclared dimensions `platform` и `acquisition_channel` сверяются с protocol
  `segment_policy`, а post-hoc `country` остается `exploratory_only`;
- `platform=android` имеет обе ветки и lift `-0.666667`, но не проходит
  протокольный minimum cell size `500`, поэтому остается diagnostic layer;
- `acquisition_channel` показывает типичный failure mode segment analysis на tiny:
  большинство строк получает `missing_variant`, потому что внутри сегмента нет одной из
  веток;
- все interaction checks получают `insufficient_overlap`, segment findings явно не
  становятся launch gates;
- lesson suite содержит 10 behavioral tests.

Урок `10/11` «Протокол решения и коммуникация» разработан:

- добавлены `decision_policy.json`, `experiment_decision_packager.py` и committed
  `experiment-decision-package/` с evidence, assignment audit, decision summary,
  markdown report, checksums и manifest;
- package собирает protocol, assignment/exposure evidence, A/A/SRM, power, raw effects,
  assumption checks, bootstrap intervals, CUPED report, multiple-testing policy/report,
  peeking audit и segment report;
- generated `assignment_audit.json` подтверждает one-unit-one-variant и соответствие
  exposure назначенному варианту: `5` assigned units, `5` exposed units,
  `control=3`, `treatment=2`;
- итоговое решение `hold`: launch запрещен из-за `missed_primary_direction`,
  `observed_sample_below_power_plan`, `multiple_testing_does_not_allow_launch`,
  unplanned decision looks и segment diagnostics; rollback не нужен, потому что
  guardrails имеют статус `watch`, а не breach;
- checksum manifest фиксирует SHA-256 digest для `23` package files и digest самого
  `checksums.json` в `manifest.json`;
- lesson suite содержит 10 behavioral tests.

## Фаза 11

Фаза 11 спроектирована в `docs/phase-11-design.md`: зафиксированы границы analytics
engineering, роли dbt Core/local CLI, dbt-duckdb, DuckDB, SQLFluff, PyYAML/Pydantic и
pytest, общий customer revenue health mart, source/model/snapshot failure modes,
machine-readable mart contract и структура финального `analytics-mart-dbt/` package.

Урок `11/01` «Слои и контракты аналитических данных» разработан:

- добавлен общий tiny extract фазы 11: `raw_users`, `raw_events`, `raw_orders`,
  `raw_order_items`, `raw_subscriptions`, `raw_support_tickets`, `raw_refunds`,
  `raw_currency_rates` и `data/contract.json`;
- добавлены `layer_contract.json`, `mart_design_brief.md`,
  `layer_contract_auditor.py` и committed `layer_contract_audit.json`;
- аудитор проверяет uniqueness model ids, required fields, allowed layers/materializations,
  source tables against data contract, raw primary keys, upstream graph, direct raw-to-mart
  skips, key tests, freshness, mart publication contract, limitations и design brief;
- lesson suite содержит 11 behavioral tests.

Урок `11/02` «Структура dbt-проекта» разработан:

- добавлен `dbt_project_skeleton/` с `dbt_project.yml`, `profiles.yml.example`,
  `commands.md`, каталогами `models/`, `tests/`, `macros/`, `snapshots/`, `seeds/` и
  smoke graph `staging -> intermediate -> marts`;
- locked runtime дополнен `dbt-core==1.11.11` и `dbt-duckdb==1.10.1`;
- добавлен `dbt_project_auditor.py` и committed `dbt_project_audit.json`;
- аудитор проверяет required project files, project/profile match, resource directories,
  smoke models per layer, local DuckDB profile, отсутствие secret-like fields,
  документацию команд `debug`/`parse`/`compile` и умеет запускать эти команды во
  временной копии проекта;
- lesson suite содержит 11 behavioral tests.

Урок `11/03` «Sources, refs и зависимости» разработан:

- добавлен `source_ref_project/` с 8 raw tables, объявленными как dbt sources через
  `raw_app`, `identifier` и table-level `loaded_at_field`/freshness config;
- staging-модели `stg_users`, `stg_orders`, `stg_order_items` читают raw только через
  `source()`;
- `int_order_line_revenue` и `mart_customer_revenue_health` строят downstream graph через
  `ref()` без direct raw references;
- добавлен `source_ref_lineage_auditor.py` и committed `source_ref_lineage_audit.json`;
- аудитор проверяет source declarations against data contract, freshness config,
  `source()`/`ref()` boundaries, отсутствие hardcoded `raw_*` в SQL, а в live mode
  поднимает временную DuckDB-базу, запускает `dbt parse`, `dbt compile`,
  `dbt source freshness` и сверяет manifest dependencies;
- lesson suite содержит 10 behavioral tests.

Урок `11/04` «Модели и materializations» разработан:

- добавлен `materialization_project/` с 13 моделями: 8 staging views, 2 intermediate
  ephemeral models, 2 reusable intermediate views и consumer-facing table
  `mart_customer_revenue_health`;
- materialization policy хранится в `models/properties.yml`: для каждой модели объявлены
  `config.materialized`, layer, grain, consumer, materialization reason и cost note;
- mart объединяет users, orders, order_items, refunds, subscriptions, support tickets и
  currency rates, переводит USD order в RUB и сохраняет grain «один активный
  неудаленный пользователь»;
- добавлен `materialization_reporter.py` и committed `materialization_report.json`;
- аудитор проверяет source/ref boundaries, отсутствие direct raw references,
  documented materialization decisions, запрет incremental/materialized_view до
  следующих уроков, ограниченный fanout ephemeral-моделей, live `dbt parse`,
  targeted `dbt compile`, `dbt run`, physical relation counts, compiled ephemeral CTE
  names и independent mart reconciliation;
- lesson suite содержит 10 behavioral tests.

Урок `11/05` «Data tests» разработан:

- добавлен `data_test_project/` на базе mart-графа из `11/04` с 64 generic data tests
  для `not_null`, `unique`, `relationships` и `accepted_values`;
- добавлены 3 singular tests: `assert_paid_revenue_reconciles`,
  `assert_no_many_to_many_revenue_join` и non-blocking
  `warn_customers_without_subscription`;
- source freshness настроена для всех 8 raw sources по `loaded_at_field` из phase data
  contract;
- добавлен `dbt_test_reporter.py` и committed `dbt_test_report.json`;
- аудитор проверяет использование `data_tests` вместо legacy `tests`, наличие generic
  families, документацию singular tests, `severity: warn` для warning diagnostics,
  mart policy в `meta.required_tests`/`meta.warning_checks`, live `dbt parse`, `dbt run`,
  `dbt source freshness`, `dbt test --select test_type:data`, dbt artifacts и разделение
  contract failures от warnings;
- lesson suite содержит 11 behavioral tests, включая мутации bad order status, orphan
  relationship и paid revenue reconciliation drift.

Урок `11/06` «Jinja и macros без злоупотребления» разработан:

- добавлен `macro_project/` на базе mart/test графа из `11/05`;
- добавлены 5 documented low-level macros в `macros/normalization.sql`:
  `normalize_status`, `normalize_currency`, `to_decimal`, `money_product` и
  `rub_amount`;
- `macros/properties.yml` документирует descriptions, arguments, types и review rules;
- `revenue_health_segment` и paid/refund business policy оставлены в mart-модели, а не
  спрятаны в macro;
- добавлен `compiled_sql_review_checklist.json`, `macro_review_auditor.py` и committed
  `macro_review_report.json`;
- аудитор проверяет macro definitions, matching documented arguments, intentional call
  counts, whitespace control, запрет business-policy macros, live `dbt parse`,
  `dbt compile`, `dbt run`, `dbt test --select test_type:data`, отсутствие Jinja в
  compiled model SQL, expected compiled fragments и mart baseline
  `row_count=5`/`paid_revenue_rub=4312.50`;
- lesson suite содержит 10 behavioral tests, включая поломки macro docs, bypass
  inline SQL, скрытую business macro, compiled SQL drift и неправильную RUB conversion.

Урок `11/07` «Инкрементальные модели» разработан:

- добавлен `incremental_project/` на базе dbt-графа из `11/06`;
- добавлена incremental fact-модель `fct_order_revenue_daily` с grain
  `revenue_date`, `unique_key='revenue_date'`, strategy `delete+insert`,
  `is_incremental()` predicate через `{{ this }}` и двухдневным late-arrival window;
- `models/properties.yml` содержит `incremental_contract` в `meta`: event time column,
  unique key, late-arrival window, schema change policy, duplicate policy,
  full-refresh policy и backfill command;
- добавлены singular test `assert_daily_revenue_reconciles.sql`,
  `backfill_full_refresh_playbook.md`, `incremental_model_auditor.py` и committed
  `incremental_audit_report.json`;
- аудитор проверяет статический contract, data tests на unique key, playbook, live
  начальный full refresh, обычный incremental run с новой датой и поздним заказом,
  отсутствие дублей по `revenue_date`, compiled SQL без Jinja и документированный
  `--full-refresh`;
- lesson suite содержит 9 behavioral tests, включая поломки `unique_key`,
  `is_incremental()`/`{{ this }}`, late-arrival window, meta contract, unique/not_null
  tests и full-refresh playbook.

Урок `11/08` «Snapshots и история изменений» разработан:

- добавлен `snapshot_project/` на базе dbt-графа из `11/07`;
- добавлен YAML snapshot `subscription_status_snapshot` для `stg_subscriptions`:
  `unique_key=subscription_id`, `strategy=check`, `updated_at=updated_at`,
  `check_cols=[plan,status,started_at,ended_at]`, `dbt_valid_to_current=9999-12-31`;
- `updated_at` исключен из `check_cols`, чтобы шумный source reload не создавал новую
  SCD-версию без бизнес-изменения;
- добавлена downstream-модель `int_subscription_history`, которая нормализует
  `dbt_valid_from`, `dbt_valid_to`, `dbt_scd_id` и `is_current`;
- добавлены singular tests: `assert_subscription_history_has_one_current_row`,
  `assert_subscription_history_windows_do_not_overlap`,
  `assert_snapshot_does_not_version_noisy_updated_at`;
- добавлены `snapshot_history_runbook.md`, `snapshot_history_auditor.py` и committed
  `snapshot_history_audit_report.json`;
- аудитор проверяет YAML snapshot configs, запрет legacy SQL snapshots, source key tests,
  snapshot meta column tests, runbook schedule/hard delete policy, staging timestamp
  safety, live первый `dbt snapshot` и второй snapshot с бизнес-изменениями/шумным
  `updated_at`;
- lesson suite содержит 10 behavioral tests, включая поломки `unique_key`, `updated_at`,
  `check_cols: all`, шумного `updated_at` в `check_cols`, legacy SQL snapshot,
  history model contract, staging timestamp safety и runbook.

Урок `11/09` «Документация и lineage» разработан:

- добавлен `documentation_project/` на базе dbt-графа из `11/08`;
- добавлены docs blocks для project overview, `mart_customer_revenue_health`,
  `int_subscription_history` и `customer_revenue_health_dashboard`;
- sources, key models, snapshot columns и singular data tests получили descriptions,
  owners, grain/consumer metadata и freshness context;
- добавлен exposure `customer_revenue_health_dashboard` с owner, maturity, URL,
  `depends_on` на `mart_customer_revenue_health`, `fct_order_revenue_daily`,
  `int_subscription_history` и machine-readable decision claims;
- добавлен `documentation_lineage_auditor.py` и committed
  `documentation_lineage_report.json`;
- аудитор проверяет static docs contract, запрет прямой raw-source зависимости в exposure,
  claims-to-models/tests mapping, live `dbt parse`/`run`/`snapshot`/`test`/`docs generate`,
  `manifest.json`, `catalog.json`, docs blocks, exposure lineage и catalog columns;
- lesson suite содержит 10 behavioral tests, включая поломки owner, raw dependency,
  docs block, key column description, source freshness, singular test docs и CLI exit code.

Урок `11/10` «SQLFluff и единый стиль» разработан:

- добавлен `sqlfluff_project/` на базе dbt-графа `11/09`, приведенный к единому
  SQLFluff style contract;
- добавлены `.sqlfluff` с `dialect = duckdb`, `templater = dbt`, local dbt templater
  settings и `max_line_length = 120`;
- добавлены `.sqlfluffignore` для `target/`, `logs/`, `dbt_packages/` и локальных
  `*.duckdb`;
- добавлен safe local `profiles.yml` без секретов для dbt templater;
- исправлены реальные style violations: длинные Jinja macro calls, keyword-like aliases,
  qualification в reconciliation tests и layout в singular tests;
- добавлен `bad_style_example.sql` для raw-templater fast feedback;
- добавлены `sqlfluff_quality_gate.py` и committed `sqlfluff_lint_report.json`;
- аудитор проверяет static SQLFluff contract, generated ignores, safe profile,
  separation of style gate and `dbt test`, live `sqlfluff lint` на 22 SQL-файлах и
  ожидаемое падение bad style example;
- lesson suite содержит 10 behavioral tests, включая поломки templater, global ignore,
  generated ignores, keyword-like alias, profile, commands и CLI exit code;
- dev environment дополнен `sqlfluff==3.5.0` и `sqlfluff-templater-dbt==3.5.0`.

Урок `11/11` «Локальный проект с dbt-duckdb» разработан:

- добавлен финальный пакет `analytics-mart-dbt/` с `dbt_project.yml`, safe local
  DuckDB profile, `.sqlfluff`, `.sqlfluffignore`, sources, staging/intermediate/mart
  models, macros, tests, snapshot, seed `calendar.csv`, `docs/mart_contract.md` и
  `commands.md`;
- добавлен `analytics_mart_packager.py`, который загружает fixture CSV в DuckDB, запускает
  `dbt parse`, `dbt run`, `dbt snapshot`, `dbt test`, `dbt docs generate` и
  `sqlfluff lint`, затем обновляет release artifacts;
- пакет содержит `target-artifacts/manifest.json`, `catalog.json`, `run_results.json`,
  `lineage-summary.json`, `quality/dbt-test-report.json`, `source-freshness.json`,
  `sqlfluff-report.json`, `contract-audit.json`, `report.md` и SHA-256 `manifest.json`;
- live build проходит: 15 моделей, 1 seed, 1 snapshot, 8 sources, 1 exposure, 87 dbt
  data tests (`86 pass`, `1 warn`), SQLFluff lint на 22 SQL-файлах без нарушений;
- lesson suite содержит 8 behavioral tests, включая live build на временной копии,
  запрет direct raw references, incremental late-window contract, dbt templater,
  report-to-manifest traceability, checksum tampering и CLI exit code.

## Фаза 12

Фаза 12 спроектирована в `docs/phase-12-design.md`: зафиксированы границы
performance-фазы, роли Python profiling tools, pandas, PyArrow/Arrow, DuckDB, Polars,
Ibis, NumPy, Pandera/Pydantic и pytest, общий `customer_revenue_health_weekly` pipeline,
failure modes benchmark/data layout/interoperability, machine-readable benchmark scenario
contract и структура финального `performance-benchmark-package/`.

Уроки фазы 12 развернуты в `curriculum.json`: `12/01`-`12/11` завершены.

- `12/01` «Корректный benchmarking»: benchmark harness, environment report,
  equivalence gate; разработан полный lesson package с `benchmark_harness.py`,
  behavioral tests, quiz, docs и artifact manifest;
- `12/02` «CPU и memory profiling»: разработан полный lesson package с
  `profiling_report.py`, `cProfile`, `tracemalloc`, wall/process time,
  hot-spot classifier, memory budget findings, behavioral tests, quiz, docs и
  artifact manifest;
- `12/03` «Память и типы данных»: разработан полный lesson package с
  `dtype_policy.py`, pandas `memory_usage(deep=True)`, safe integer downcast,
  category/domain checks, nullable fields, memory budget findings, behavioral tests,
  quiz, docs и artifact manifest;
- `12/04` «Projection и predicate pushdown»: разработан полный lesson package с
  `parquet_pushdown_audit.py`, Hive-partitioned Parquet layout, PyArrow Dataset scan,
  DuckDB `EXPLAIN`, file/row-group pruning audit, result contract, behavioral tests,
  quiz, docs и artifact manifest;
- `12/05` «Arrow memory model»: разработан полный lesson package с
  `arrow_memory_inspector.py`, PyArrow Table/Array buffer inspector, null bitmap,
  offsets, chunked arrays, dictionary encoding, zero-copy/copy boundary audit,
  behavioral tests, quiz, docs и artifact manifest;
- `12/06` «DuckDB и данные больше памяти»: разработан полный lesson package с
  `duckdb_out_of_core_report.py`, генератором Parquet workload, DuckDB
  `memory_limit`/`temp_directory`/`threads`, `EXPLAIN`/`EXPLAIN ANALYZE`, классификацией
  blocking operators, spill observation, pandas equivalence gate, runbook, behavioral
  tests, quiz, docs и artifact manifest;
- `12/07` «Polars expressions»: разработан полный lesson package с
  `polars_expression_pipeline.py`, Polars `select`/`with_columns`/`filter`/`group_by`
  expression pipeline, pandas control, schema report, row-wise Python UDF audit,
  equivalence gate, behavioral tests, quiz, docs и artifact manifest;
- `12/08` «Lazy execution и оптимизация»: разработан полный lesson package с
  `polars_lazy_plan_audit.py`, широким Parquet input, `pl.scan_parquet` lazy pipeline,
  optimized/unoptimized `LazyFrame.explain`, projection/predicate pushdown audit,
  early `collect`/Python UDF source audit, pandas equivalence gate, behavioral tests,
  quiz, docs и artifact manifest;
- `12/09` «Streaming и пакетная обработка»: разработан полный lesson package с
  `streaming_batch_processor.py`, Parquet batch manifest и SHA-256 identity,
  additive partial state, атомарным checkpoint через `os.replace`, simulated
  interruption/resume без двойного учета, классификацией bounded/mergeable operations,
  median-of-medians counterexample, pandas и Polars streaming equivalence gates,
  behavioral tests, quiz, docs и artifact manifest;
- `12/10` «Обмен между pandas, Arrow и Polars»: разработан полный lesson package с
  `interoperability_audit.py`, каноническим Arrow schema contract, pandas ArrowDtype
  storage audit, buffer-address reuse checks, Polars string/category re-encoding,
  DuckDB Arrow materialization и dictionary decode, timezone session counterexample,
  interoperability matrix, engine-boundary decision, behavioral tests, quiz, docs и
  artifact manifest;
- `12/11` «Ibis как переносимый DataFrame API»: разработан интеграционный
  `performance-benchmark-packager` на Ibis `12.0.0`; один portable core компилируется
  в DuckDB SQL и Polars `LazyFrame`, проходит equivalence gate вместе с pandas,
  native DuckDB и native Polars, а неподдержанное dense-rank окно Polars backend
  фиксируется как явная divergence; пакет сохраняет raw runs, summary, планы,
  CPU/memory profiles, portability audit, динамическое engine decision и SHA-256
  manifest; lesson suite содержит 16 behavioral tests.

Для `12/07` добавлен runtime Polars `1.41.2`, для `12/11` — Ibis `12.0.0` с DuckDB и
Polars extras; версии зафиксированы в `pyproject.toml` и `uv.lock`.

Фазы 00–12 завершены.

## Фаза 13

Фаза 13 спроектирована в `docs/phase-13-design.md`: зафиксированы границы со статистикой,
экспериментами, временными рядами и ML, роли statsmodels, NetworkX, DoWhy и optional
EconML, единая задача assisted onboarding, causal study spec, failure modes
identification/adjustment/overlap/quasi-experiments и структура итогового
`causal-study-package`.

Уроки `13/01`–`13/11` развернуты в `curriculum.json` как последовательность на
930 минут:

- `13/01` — causal question, target trial-style contract и ATE/ATT/LATE estimand;
- `13/02` — causal DAG, temporal order, d-separation и identification map;
- `13/03` — confounders, backdoor paths и adjustment-set audit;
- `13/04` — colliders, mediators, post-treatment controls и selection bias;
- `13/05` — regression adjustment, standardization и g-formula;
- `13/06` — matching, common support и balance diagnostics;
- `13/07` — propensity weighting, effective sample size и AIPW;
- `13/08` — 2x2/multi-period DiD, pre-trends, event-study и staggered-adoption risk;
- `13/09` — RDD/IV design audit, local estimands, cutoff manipulation и weak instrument;
- `13/10` — placebo, negative controls и omitted-confounding sensitivity;
- `13/11` — DoWhy workflow, EconML scope audit и интеграционный
  `causal-study-package`.

Урок `13/01` «Причинный вопрос и estimand» разработан:

- добавлен общий dataset фазы с `users`, `pre_treatment_behavior`,
  `onboarding_assistance`, `outcomes`, `encouragement_assignments`,
  `rollout_calendar`, `region_week_panel`, `causal_scenarios`, контрактом,
  deterministic `tiny` и локальным `sample` generator;
- tiny-profile содержит 13 users, из которых target population включает 10:
  6 treated и 4 comparator; treatment starts после общего time zero и внутри
  24-часового grace period;
- `causal_question.json`, `target_trial_spec.json` и `estimand.json` фиксируют
  population, strategies, time zero, outcomes, ATE, risk difference и четыре
  assumptions;
- `causal_question_validator.py` проверяет IDs, data contract, timing-safe eligibility,
  treatment versions, ATE/ATT/LATE population semantics, assumptions, grain,
  treatment/follow-up chronology и блокирует effect claim до identification;
- валидный отчет намеренно сохраняет warning
  `observational_assignment_requires_identification`;
- lesson suite содержит 14 behavioral tests.

Урок `13/02` «Причинные DAG и идентификация» разработан:

- `causal_dag.json` фиксирует 19 узлов и 44 causal edges для assisted onboarding,
  включая observed baseline confounders, mediator, collider, selection variable и
  unmeasured `latent_motivation`;
- `identification_map.json` связывает DAG с estimand `13/01`, разделяет association
  `P(Y | T)` и intervention `P(Y | do(T))`, описывает removed incoming treatment edges,
  candidate adjustment sets и d-separation checks;
- `causal_dag_validator.py` проверяет required fields, уникальность узлов, unknown edge
  endpoints, acyclicity, temporal order, required causal roles, alignment с question/
  estimand, d-separation claims, active backdoor paths, forbidden controls и premature
  estimator/identified claims;
- валидный audit сохраняет warning
  `unmeasured_confounding_blocks_backdoor_identification`: measured baseline controls
  оставляют открытым путь `assisted_within_24h <- latent_motivation -> activation_14d`;
- lesson suite содержит 17 behavioral tests.

Урок `13/03` «Confounders и backdoor adjustment» разработан:

- `confounder_inventory.json` перечисляет 11 measured baseline confounders,
  unmeasured `latent_motivation`, proxy variables и forbidden controls для total-effect
  question;
- `adjustment_set_spec.json` сравнивает naive, too-narrow, recommended measured,
  oracle latent и bad-control candidate sets и фиксирует claim policy
  `not_identified_due_to_unmeasured_confounding`;
- `backdoor_adjustment_auditor.py` переиспользует ручной d-separation engine из `13/02`
  и проверяет source fields в data contract, active backdoor path participation,
  measured/unmeasured status, forbidden mediator/collider/selection controls,
  consistency declared/calculated statuses, ровно один primary recommendation и запрет
  causal effect claim при remaining unmeasured path;
- валидный audit показывает 48 active backdoor paths без adjustment, 11 measured
  confounders, 1 unmeasured confounder, primary set
  `measured_baseline_backdoor_set`, 0 open measured paths и 1 open unmeasured path после
  primary adjustment;
- lesson suite содержит 15 behavioral tests.

Урок `13/04` «Colliders, mediators и selection bias» разработан:

- `bad_control_policy.json` фиксирует forbidden controls для primary total-effect
  question: assignment mechanism `offered_assistance`, mediator
  `onboarding_completed_48h`, collider `opened_support_chat_after_offer`, selection
  variable `telemetry_complete_30d`, primary outcome `activation_14d` и downstream
  outcome `paid_subscription_30d`;
- `candidate_control_actions.json` сравнивает allowed observed baseline handoff,
  offer split, mediator adjustment, support-chat filter, telemetry complete-case filter,
  post-treatment feature soup и outcome leakage candidates;
- `bad_control_selection_auditor.py` переиспользует d-separation engine из `13/02`,
  проверяет policy coverage по DAG roles/timing/descendants, source fields в data
  contract, declared/calculated statuses, population-change notes для filters,
  primary action без bad controls и запрет bad-control actions для future estimators;
- валидный audit показывает 50 active total paths, 48 active backdoor paths, 2 directed
  total-effect paths, единственный allowed action `recommended_pre_treatment_set`,
  0 open measured и 1 open unmeasured backdoor path после primary handoff;
- report содержит mechanism examples: mediator blocking directed total-effect path,
  collider-opened support-chat paths и selection-opened telemetry paths;
- lesson suite содержит 16 behavioral tests.

Урок `13/05` «Regression adjustment и g-formula» разработан:

- `g_formula_spec.json` фиксирует outcome-regression estimator для target trial и
  estimand из `13/01`, handoff из bad-control gate `13/04`, source coverage для
  recommended pre-treatment adjustment set и запрет causal effect claim при remaining
  unmeasured confounding;
- `g_computation_estimator.py` собирает target-population cohort, проверяет grain,
  timing, treatment arms, follow-up, model source policy, bad-control candidates,
  declared candidate statuses и claim policy;
- валидный `g_formula_estimate_report.json` показывает cohort 10 users, naive
  risk difference `-0.08333333333333337`, manual OLS и statsmodels ATE/ATT
  `-0.39978100191623295`, standardized potential outcomes и warnings по LPM
  probability bounds и counterfactual support;
- lesson suite содержит 16 behavioral tests: ручная OLS сверяется со statsmodels,
  standardization использует те же cohort rows, bad-control/source leakage блокируется,
  duplicate source grain возвращает structured invalid report, timing вне grace period
  и неверный claim policy дают отказ.

Урок `13/06` «Matching и баланс ковариат» разработан:

- `matching_spec.json` фиксирует nearest-neighbor ATT matching для target trial и
  estimand из `13/01`, handoff из bad-control gate `13/04`, distance features
  `friction_score` и `specialist_capacity`, standardized Euclidean distance, caliper
  `1.5`, replacement policy и запрет causal effect claim при remaining unmeasured
  confounding;
- `matching_pipeline.py` собирает target-population cohort, проверяет grain, timing,
  treatment arms, follow-up, matching source policy, candidate design statuses, claim
  policy, ручную distance matrix против `scipy.spatial.distance.cdist`, matched pairs,
  common support и balance diagnostics;
- валидный `matching_report.json` показывает cohort 10 users, 6 treated, 4 comparators,
  naive risk difference `-0.08333333333333337`, 4 matched treated, 2 unmatched treated
  (`U001`, `U002`), reuse control `U005`, matched ATT `-0.25`, balance/love plot data и
  warnings по unmatched support, post-match balance threshold и worsened balance;
- lesson suite содержит 16 behavioral tests: matched pairs и replacement deterministic,
  distance matrix сверяется со SciPy, common-support warning перечисляет unmatched users,
  bad-control/source leakage блокируется, duplicate source grain возвращает structured
  invalid report, timing вне grace period и неверный claim policy дают отказ.

Урок `13/07` «Propensity weighting и doubly robust оценка» разработан:

- `ipw_aipw_spec.json` фиксирует primary ridge propensity model, outcome model из
  observed-baseline basis, diagnostics для overlap, weights, ESS и trimming, stress
  tests для misspecified treatment/outcome models и claim policy;
- `ipw_aipw_estimator.py` собирает target-population cohort, проверяет grain, timing,
  follow-up, source coverage, bad controls, candidate statuses, ridge logistic propensity
  solver, stabilized/unstabilized weights, HT/Hájek IPW, AIPW residual correction,
  trimming sensitivity и сверку ручной OLS со statsmodels;
- валидный `ipw_aipw_report.json` показывает cohort 10 users, naive risk difference
  `-0.08333333333333337`, IPW Hájek `-0.08519236630007954`, IPW HT
  `0.07893418528076585`, AIPW `-0.3868752937879506`, outcome-regression ATE
  `-0.399781001916233`, overlap tail по `U001`, ESS `9.555331641172497` и trimming
  population-change warnings;
- lesson suite содержит 19 behavioral tests: unit-level propensity/weights,
  manual AIPW reconstruction, trimming sensitivity, stress tests, bad-control/source
  gates, duplicate grain, timing/follow-up failures и CLI `--fail-on-invalid`.

Урок `13/08` «Difference-in-Differences» разработан:

- `did_spec.json` фиксирует региональный rollout design: north starts `2026-07-06`,
  south starts `2026-07-20`, primary 2x2 contrast north versus not-yet-treated south,
  pretrend, fake rollout placebo, mean-friction composition placebo, event-study policy,
  TWFE diagnostic и candidate design statuses;
- `did_analyzer.py` проверяет grain `region_id + week_start`, rollout calendar,
  scenario registry, not-yet-treated control status, считает four-cell manual DiD,
  saturated 2x2 regression reconciliation, pretrend slopes, placebo checks, event-study
  table и full-panel TWFE coefficient через manual dummy matrix со statsmodels check;
- валидный `did_report.json` показывает treated change `0.105`, control change
  `0.025`, DiD `0.08000000000000002`, fake pre-period placebo `0.0`, pretrend slope
  difference `2.7755575615628914e-17`, sparse event times `[-5, -4, 3, 4]`, TWFE
  coefficient `0.07999999999999921` и warnings по sparse tails и diagnostic-only TWFE;
- lesson suite содержит 17 behavioral tests: 2x2 accounting, saturated regression,
  pretrend/placebo checks, event-study sparse tails, TWFE diagnostic, candidate design
  policy, duplicate region-week, calendar mismatch, already-treated control, failed
  pretrend/placebo claim blocking, scenario alignment и CLI `--fail-on-invalid`.

Урок `13/09` «RDD и instrumental variables: дизайн до оценки» разработан:

- `quasi_experiment_spec.json` фиксирует два quasi-experimental candidates:
  fuzzy RDD около cutoff `friction_score >= 60` с bandwidth `8` и IV design
  `capacity_encouragement_late` с instrument `encouraged`, treatment
  `received_assistance`, outcome `activation_14d` и estimand `LATE`;
- `quasi_experiment_design_auditor.py` проверяет declared source grain, scenario
  registry, RDD local support, local estimand, sharp-vs-fuzzy assignment, simple
  density/manipulation screen, pre-treatment continuity, IV first stage, LATE contract,
  observed balance, recorded exclusion/monotonicity assumptions и candidate design
  statuses;
- валидный `quasi_experiment_report.json` показывает RDD local rows `6`, side counts
  `3/3`, fuzzy first stage `0.6666666666666667`, reduced form
  `-0.6666666666666667`, diagnostic local Wald `-1.0`, IV rows `10`, IV first stage
  `0.4`, reduced form `0.20000000000000007`, Wald LATE `0.5000000000000001`,
  allowed local/LATE claim wording и warnings `rdd_tiny_wald_estimate_is_diagnostic_only`
  и `iv_exclusion_and_monotonicity_cannot_be_proven_from_observed_data`;
- lesson suite содержит 16 behavioral tests: expected RDD/IV numbers, runnable example,
  fuzzy assignment violation, local window, density/continuity screens, IV first stage
  и LATE, candidate status policy, cutoff bunching, narrow bandwidth, covariate jump,
  weak instrument, LATE-to-ATE overclaim, duplicate grain, scenario alignment и CLI
  `--fail-on-invalid`.

Урок `13/10` «Sensitivity analysis и falsification checks» разработан:

- `sensitivity_spec.json` фиксирует primary AIPW effect из `13/07`, upstream reports
  `13/07`/`13/08`/`13/09`, target population, placebo treatment/outcome,
  negative-control outcome, upstream DiD placebo, omitted-confounding grid,
  candidate claim statuses и claim policy;
- `sensitivity_refutation_suite.py` проверяет source grain, target population,
  доступность upstream reports, запускает falsification checks, строит sensitivity grid,
  сравнивает RA/IPW/AIPW, DiD, RDD и IV estimates без pooling и переводит diagnostics в
  claim policy;
- валидный `sensitivity_report.json` показывает cohort `10`, primary AIPW effect
  `-0.3868752937879506`, falsification failures
  `placebo_outcome_pre_activation` и `negative_control_outcome_app_crashes`, required
  bias to reach null `0.3868752937879506`, first nulling bias `0.4`, design estimate
  range `1.5`, opposite signs across designs и `allowed_effect_claim = false` с
  reasons `falsification_checks_failed`, `upstream_primary_claim_disallowed`,
  `design_estimates_have_opposite_signs`, `different_estimands_not_poolable`;
- lesson suite содержит 15 behavioral tests: blocked strong claim policy, runnable
  example, placebo treatment pass, placebo outcome и negative-control failures,
  upstream DiD placebo propagation, omitted-confounding nulling scenario, cross-design
  no-pooling, candidate claim statuses, relaxed threshold, duplicate source grain,
  empty target population, missing upstream report, CLI `--fail-on-invalid` и committed
  report reproducibility.

Урок `13/11` «Causal workflow и границы автоматизации» разработан:

- `causal_workflow_spec.json` фиксирует package contract, 15 upstream source files,
  обязательные секции question/model/identify/estimate/refute/automation/evidence/
  checksum, DoWhy workflow order и runtime policy без добавления тяжелой optional
  dependency;
- `causal_study_package_builder.py` собирает воспроизводимый
  `causal_study_package.json`, checksum manifest, estimate comparison table,
  refutation handoff, evidence statement и automation audit;
- валидный package показывает 15 source files, 7 design-specific estimate rows,
  DoWhy-compatible trace `model -> identify -> estimate -> refute`,
  `econml_used = false`, `allowed_effect_claim = false` и финальный статус
  `blocked_single_strong_claim`;
- package явно не усредняет несовместимые ATE/ATT/LATE/local estimates, не превращает
  unmeasured-confounding block в identified claim и не использует EconML без отдельного
  heterogeneity/CATE/policy-learning вопроса;
- lesson suite содержит 14 behavioral tests: section/checksum contract, preservation of
  question/model/identification, no-pooling policy, sensitivity-aligned evidence
  statement, DoWhy trace order, automation boundaries, reproducibility, missing/invalid
  upstream sources, wrong workflow order, too-strong final claim и CLI
  `--fail-on-invalid`.

## Фаза 14

Фаза 14 спроектирована в `docs/phase-14-design.md`: зафиксированы границы с продуктовой
аналитикой, статистикой, причинным анализом, ML и delivery, роли pandas, NumPy, SciPy,
statsmodels, DuckDB, Pandera/Pydantic и визуализаций, единая forecasting-задача по
активным подпискам, net revenue и нагрузке на поддержку, forecast scenario spec, failure
modes time index/resampling/leakage/backtesting/metrics/intervals/anomalies и структура
итогового `time-series forecast package`.

Уроки `14/01`–`14/12` развернуты в `curriculum.json` как последовательность на
945 минут; все 12 уроков завершены:

- `14/01` — временной индекс, timezone, frequency, observation window и calendar grain:
  завершен как `time-index-auditor` с общим tiny dataset, manifest и 10 behavioral tests;
- `14/02` — resampling, aggregation policy, complete-period policy и reconciliation:
  завершен как `resampling-pipeline` с `subscription_events.csv`, resampling spec,
  daily/weekly outputs, reconciliation table, partial-period audit и 11 behavioral tests;
- `14/03` — rolling/expanding windows, lag policy и leakage checks:
  завершен как `window-feature-builder` с `window_feature_spec.json`,
  `window_features.csv`, `leakage_audit.csv`, warmup/partial policy и 12 behavioral
  tests;
- `14/04` — trend, seasonality, calendar/campaign/release effects:
  завершен как `seasonality-profiler` с `seasonality_profile_spec.json`,
  `trend_summary.csv`, `seasonality_profile.csv`, `calendar_effect_inventory.csv`,
  known-before-origin gates и 13 behavioral tests;
- `14/05` — forecast origin, horizon, data availability и temporal leakage audit:
  завершен как `temporal-leakage-auditor` с `temporal_leakage_spec.json`,
  `cutoff_contract.json`, `forbidden_feature_report.csv`, `temporal_leakage_report.json`,
  gates для cutoff/embargo/feature availability/calendar known-before-origin/revisions
  и 14 behavioral tests;
- `14/06` — naive, seasonal naive, drift и moving-average baselines:
  завершен как `baseline-forecaster` с `baseline_forecast_spec.json`,
  `baseline_forecasts.csv`, `baseline_trace.csv`, `baseline_report.json`,
  seasonal-naive primary baseline policy, forecast anchors trace и 15 behavioral tests;
- `14/07` — STL decomposition, component tables и residual diagnostics:
  завершен как `stl-decomposition-reporter` с `decomposition_spec.json`,
  `decomposition_components.csv`, `residual_diagnostics.csv`,
  `decomposition_report.json`, additive STL reconstruction, residual diagnostics,
  diagnostic-only policy и 15 behavioral tests;
- `14/08` — ETS и ARIMA/SARIMAX candidate models в statsmodels:
  завершен как `statsmodels-forecast-runner` с `statsmodels_model_spec.json`,
  `candidate_forecasts.csv`, `model_diagnostics.csv`, `library_vs_baseline.csv`,
  `model_report.json`, predeclared model spec, warnings/convergence propagation,
  shape-only baseline comparison и 15 behavioral tests;
- `14/09` — rolling-origin backtesting:
  завершен как `rolling-origin-backtester` с `backtesting_spec.json`,
  `backtest_observations.csv`, `split_manifest.csv`, `backtest_forecasts.csv`,
  `backtest_errors.csv`, `backtest_report.json`, expanding/rolling origins,
  fixed horizon, gap/embargo checks, refit_each_origin policy и 14 behavioral tests;
- `14/10` — MAE/RMSE/MAPE/sMAPE/WAPE/MASE и metric suitability audit:
  завершен как `forecast-metric-evaluator` с `forecast_metric_spec.json`,
  `forecast_metrics.csv`, `metric_suitability_audit.csv`, `mase_denominators.csv`,
  `metric_leaderboard.csv`, `metric_report.json`, overall/segment/horizon slices,
  weighted-MASE leaderboard policy, zero-denominator handling и 14 behavioral tests;
- `14/11` — residual/bootstrap/model-based prediction intervals и coverage report:
  завершен как `prediction-interval-calibrator` с `prediction_interval_spec.json`,
  `interval_forecasts.csv`, `interval_backtest_predictions.csv`,
  `interval_coverage.csv`, `interval_calibration_audit.csv`, `interval_report.json`,
  empirical coverage, horizon extrapolation policy, uncertainty statements и 15
  behavioral tests;
- `14/12` — anomaly policy и интеграционный `time-series forecast package`:
  завершен как `time-series-forecast-packager` с `forecast_package_spec.json`,
  `anomaly_flags.csv`, `quality_gate_summary.csv`, `anomaly_policy.json`,
  `forecast_package_report.json`, `decision_report.md`,
  `forecast_package_manifest.json`, explicit anomaly labels, upstream warning
  propagation, no-causal-claim boundary и 13 behavioral tests.

Фазы 16-18 завершены: табличный ML заканчивается interpretation/stability package,
delivery — stakeholder handoff package, а capstone — проверенным portfolio package и
защитой. Все 19 фаз и 198 уроков имеют статус `complete`. Текущий содержательный шаг —
релизная приемка и публикация сайта; перед коммитом обязательно прогнать полный набор
проверок.

## Фаза 15

Фаза 15 завершена; дизайн зафиксирован в `docs/phase-15-design.md`: границы с
прикладной статистикой, causal inference, forecasting, production delivery и фазой 16,
единая supervised ML-задача churn-risk за 7 дней до окончания trial, problem spec,
split/metric/preprocessing/pipeline/calibration/leakage/model-card contracts и структура
итогового `ml-baseline-package`.

Уроки `15/01`–`15/15` развернуты в `curriculum.json` как последовательность на
1170 минут; все 15 уроков завершены:

- `15/01` — постановка ML-задачи: завершен как `ml-problem-spec-validator` с
  deterministic tiny churn-risk profile, machine-readable `problem_spec.json`,
  scoring snapshots, labels, feature-source inventory, readiness report,
  no-causal-claim boundary и 13 behavioral tests;
- `15/02` — train/validation/test split manifest с group/time constraints и split-role
  checks: завершен как `ml-split-auditor` с `ml_split_manifest.csv`,
  `ml_split_report.json`, eligible coverage, group isolation, chronological holdout,
  label horizon, validation/test role boundary и 15 behavioral tests;
- `15/03` — classification metrics, confusion matrix, threshold sweep и business-cost
  policy: завершен как `classification-metric-evaluator` с `ml_candidate_scores.csv`,
  `classification_metric_report.json`, validation-only threshold selection, FP/FN cost
  table, PR-oriented metrics, offer-budget gate, no-test-peeking boundary и 17
  behavioral tests;
- `15/04` — preprocessing contract: train-fitted imputation/encoding/scaling, missing
  semantics и unknown categories: завершен как `preprocessing-contract-checker` с
  `ml_raw_features.csv`, `preprocessing_contract.json`, `preprocessing_report.json`,
  `preprocessing_state.json`, `preprocessed_feature_matrix.csv`, stable transformed
  feature schema, explicit missing-value policy, unknown-category bucket audit,
  no-fit-before-split boundary и 18 behavioral tests;
- `15/05` — scikit-learn `Pipeline` как единый fit/transform/predict объект: завершен
  как `pipeline-runner` с `pipeline_spec.json`, `pipeline_report.json`,
  `pipeline_predictions.csv`, `pipeline_serialized_spec.json`, sklearn
  `Pipeline(ContractPreprocessor, LogisticRegression)`, train-only fit trace,
  validation/test probability scores, no-external-preprocessed-matrix boundary и 20
  behavioral tests;
- `15/06` — `ColumnTransformer`, feature routing и transformed schema report:
  завершен как `column-transformer-auditor` с `column_transformer_spec.json`,
  binary feature `had_support_ticket_14d`, `column_transformer_report.json`,
  `column_transformer_routing.csv`, `column_transformer_feature_schema.csv`,
  `column_transformer_predictions.csv`, `column_transformer_serialized_spec.json`,
  explicit numeric/categorical/binary routes, `remainder=drop`, stable transformed
  feature names, unknown-category bucket before `OneHotEncoder`,
  no-silent-dropped-columns boundary и 20 behavioral tests;
- `15/07` — dummy и linear/logistic baseline с coefficients и baseline comparison:
  завершен как `linear-baseline-trainer` с `linear_baseline_spec.json`,
  `baseline_report.json`, `baseline_comparison.csv`, `coefficient_table.csv`,
  `baseline_predictions.csv`, `linear_baseline_serialized_spec.json`, dummy/logistic
  sklearn `Pipeline(ColumnTransformer, estimator)`, validation-only selection,
  intercept/regularization report, coefficients joined to feature schema, explicit
  interpretation limits и 17 behavioral tests;
- `15/08` — decision tree diagnostics, overfit report и readable rules:
  завершен как `tree-diagnostic-trainer` с `tree_diagnostic_spec.json`,
  `tree_report.json`, `tree_overfit_report.csv`, `tree_node_report.csv`,
  `tree_rules.txt`, `tree_predictions.csv`, `tree_serialized_spec.json`, sklearn
  `Pipeline(ColumnTransformer, DecisionTreeClassifier)`, max-depth/min-leaf/random-state
  constraints, upstream linear-baseline handoff, train-validation gap report, readable
  rule export с transformed feature names и 17 behavioral tests;
- `15/09` — tree ensemble comparison, stability across seeds и feature-importance audit:
  завершен как `tree-ensemble-comparator` с `tree_ensemble_spec.json`,
  `ensemble_report.json`, `ensemble_comparison.csv`, `ensemble_stability_report.csv`,
  `ensemble_feature_importance.csv`, `ensemble_slice_metrics.csv`,
  `ensemble_predictions.csv`, `ensemble_serialized_spec.json`, sklearn
  `Pipeline(ColumnTransformer, RandomForestClassifier)`, validation-only comparison к
  dummy/logistic/tree baselines, stability по seeds `0/7/13`, MDI/permutation importance
  с interpretation warnings, slice metrics по `platform`/`country`, small-n warnings и
  18 behavioral tests;
- `15/10` — cross-validation planner: завершен как `cross-validation-planner` с
  `cv_plan_spec.json`, `ml_cv_fold_manifest.csv`, `cv_report.json`,
  `cv_fold_manifest.csv`, `cv_score_report.csv`, `cv_predictions.csv`,
  `cv_no_peeking_audit.csv`, `cv_serialized_spec.json`, predeclared group/time-aware
  folds, no-test-peeking audit, scoring alignment, upstream tree-ensemble handoff,
  validation-only predictions, serialized fit trace и 13 behavioral tests;
- `15/11` — imbalance policy, accuracy trap и budget-threshold report: завершен как
  `imbalance-policy-evaluator` с `imbalance_policy_spec.json`,
  `imbalance_report.json`, `class_distribution.csv`, `baseline_trap_report.csv`,
  `imbalance_threshold_report.csv`, `imbalance_predictions.csv`,
  `imbalance_policy_audit.csv`, `imbalance_serialized_spec.json`, class distribution
  report, always-negative accuracy trap, `class_weight="balanced"` candidate,
  validation-only selection, top-k vs fixed-threshold budget diagnostics и 16
  behavioral tests;
- `15/12` — probability calibration, calibration bins, Brier/log loss и threshold
  impact: завершен как `probability-calibration-auditor` с
  `calibration_policy_spec.json`, `calibration_report.json`, `calibration_bins.csv`,
  `calibration_metrics.csv`, `calibrated_predictions.csv`,
  `calibration_threshold_impact.csv`, `calibration_policy_audit.csv`,
  `calibration_serialized_spec.json`, validation-only smoothed bin-map calibrator,
  Brier/log loss/ECE comparison, calibrated vs uncalibrated top-k/fixed-threshold
  impact, no-test-calibration boundary, tiny-sample/single-class-bin warnings и 13
  behavioral tests;
- `15/13` — ML leakage audit: завершен как `ml-leakage-auditor` с
  `leakage_policy_spec.json`, `ml_feature_availability.csv`,
  `ml_feature_selection_log.csv`, `ml_model_selection_log.csv`,
  `leakage_report.json`, `feature_availability_report.csv`,
  `forbidden_feature_report.csv`, `preprocessing_scope_audit.csv`,
  `feature_selection_audit.csv`, `model_selection_audit.csv`,
  `leakage_policy_audit.csv`, `leakage_serialized_spec.json`, upstream
  probability-calibration handoff, forbidden features/post-outcome availability
  audit, train-only preprocessing gate, feature selection outside CV gate,
  validation-only model-selection gate, rejected test cherry-pick candidates и 16
  behavioral tests;
- `15/14` — segment error analysis: завершен как `segment-error-analyzer` с
  `error_analysis_policy_spec.json`, `error_analysis_report.json`,
  `confusion_rows.csv`, `slice_metrics.csv`, `small_n_warnings.csv`,
  `hidden_failure_slices.csv`, `error_examples.csv`,
  `error_analysis_policy_audit.csv`, `error_analysis_serialized_spec.json`,
  test-only calibrated confusion ledger, per-slice precision/recall/FPR/FNR/error
  rate/Brier score, small-n visibility, hidden aggregate failure warnings и 15
  behavioral tests;
- `15/15` — интеграционный model card package: завершен как `ml-baseline-packager` с
  `ml_baseline_package_spec.json`, `ml_baseline_package.json`,
  `ml_baseline_package_report.json`, `model_card.md`, `decision_report.md`,
  `evidence_matrix.csv`, `risk_register.csv`, `model_card_policy_audit.csv`,
  `ml_baseline_package_manifest.json`, 14 upstream evidence rows, 8 risk rows,
  checksum manifest, no-test-selection evidence, no-causal-offer-effect boundary,
  review-required-before-production decision и 13 behavioral tests.

Runtime-зависимость `scikit-learn` добавлена в уроке `15/05` как первая точка
использования реального sklearn API; в `uv.lock` зафиксирована версия `1.9.0`.

## Фаза 16

Фаза 16 спроектирована в `docs/phase-16-design.md`: она продолжает churn-risk задачу из
фазы 15 и превращает `ml-baseline-package` в `tabular-ml-interpretation-package`.
Границы фазы: это не повтор baseline ML, не AutoML, не causal inference, не production
monitoring и не MLOps-платформа; задача — улучшить baseline сильной табличной моделью,
сохранить честный evaluation protocol и собрать независимые объяснения.

Уроки `16/01`–`16/11` развернуты в `curriculum.json` как последовательность на 900 минут;
все 11 уроков завершены:

- `16/01` — CatBoost как сильный табличный baseline: завершен как
  `catboost-baseline-trainer` с `catboost_model_spec.json`, `catboost_report.json`,
  `catboost_comparison.csv`, `catboost_predictions.csv`, `catboost_training_trace.csv`,
  `catboost_serialized_spec.json`, native `cat_features`, train-only CatBoost fit,
  validation-only promotion gate, no-test-selection audit, baseline package warning
  propagation и 12 behavioral tests;
- `16/02` — категориальные признаки без leakage: завершен как
  `categorical-feature-auditor` с `categorical_feature_contract.json`,
  `categorical_feature_report.json`, `categorical_inventory.csv`,
  `categorical_unknowns.csv`, `categorical_leakage_audit.csv`,
  `categorical_serialized_contract.json`, handoff checks к `16/01`, explicit
  missing/unknown policies, high-cardinality и rare-level warnings,
  feature-availability/leakage gates, rejected target/full-sample/post-intervention
  categorical candidates и 13 behavioral tests;
- `16/03` — early stopping и iteration budget: завершен как
  `early-stopping-auditor` с `early_stopping_policy_spec.json`,
  `early_stopping_report.json`, `eval_set_lineage.csv`, `validation_curve.csv`,
  `tree_count_report.csv`, `early_stopping_serialized_spec.json`, validation-only
  `eval_set`, overfitting detector `Iter`, `best_iteration=0`, `tree_count=1`,
  no-test-selection gate, tiny pool/eval warnings и 14 behavioral tests;
- `16/04` — встроенная важность признаков: завершен как
  `built-in-importance-reporter` с `built_in_importance_policy_spec.json`,
  `built_in_importance_report.json`, `built_in_importance.csv`,
  `feature_name_audit.csv`, `importance_warning_ledger.csv`,
  `built_in_importance_serialized_spec.json`, CatBoost methods
  `PredictionValuesChange`/`LossFunctionChange`, feature-name order audit,
  high-cardinality/correlation/tiny-tree/dominance warnings, no-positive-causal-claim
  gate и 13 behavioral tests;
- `16/05` — permutation importance: завершен как
  `permutation-importance-evaluator` с `permutation_importance_policy_spec.json`,
  validation heldout scoring, `neg_log_loss`, 7 repeats,
  `permutation_importance_report.json`, `permutation_importance.csv`,
  `permutation_importance_repeats.csv`, `permutation_warning_ledger.csv`,
  `permutation_importance_serialized_spec.json`, no-test-peeking gate,
  repeat variance, uncertainty bands,
  high-cardinality/correlation/tiny-heldout/weak-score/no-positive-signal warnings,
  no-positive-causal-claim gate и 13 behavioral tests;
- `16/06` — SHAP и ограничения объяснений: завершен как
  `shap-explanation-reporter` с `shap_explanation_policy_spec.json`,
  `shap_explanation_report.json`, `shap_global_summary.csv`,
  `shap_local_explanations.csv`, `shap_additivity_audit.csv`,
  `explanation_disagreement.csv`, `shap_warning_ledger.csv`,
  `shap_explanation_serialized_spec.json`, TreeExplainer raw-margin explanations,
  path-dependent background reference, row-level additivity check, local/global
  summaries, disagreement table с built-in/permutation, limitation warnings и 14
  behavioral tests;
- `16/07` — сегментный анализ сильной модели: завершен как
  `strong-model-segment-analyzer` с `strong_model_segment_policy_spec.json`,
  `strong_model_segment_report.json`, `strong_model_confusion_rows.csv`,
  `strong_model_slice_metrics.csv`, `strong_model_segment_deltas.csv`,
  `strong_model_hidden_failure_slices.csv`, `strong_model_small_n_warnings.csv`,
  `strong_model_score_band_shifts.csv`, `strong_model_segment_serialized_spec.json`,
  validation-only comparison phase-15 baseline vs early-stopped CatBoost, same top-k
  budget, baseline deltas, small-n warnings, 13 hidden-failure slices, score-band shift
  warning и 10 behavioral tests;
- `16/08` — порог и стоимость решения для сильной модели: завершен как
  `cost-sensitive-decision-evaluator` с `cost_sensitive_decision_policy_spec.json`,
  `cost_sensitive_decision_report.json`, `cost_sensitive_decision_rows.csv`,
  `threshold_comparison.csv`, `budget_impact.csv`, `decision_gate.csv`,
  `cost_sensitive_decision_serialized_spec.json`, validation-only threshold selection,
  FP/FN cost policy `1/5`, top-k budget impact, candidate calibration warning,
  no-causal-offer-effect boundary, decision status `do_not_promote_catboost_candidate`
  и 9 behavioral tests;
- `16/09` — Optuna и честный подбор параметров: завершен как
  `optuna-tuning-auditor` с `optuna_tuning_policy_spec.json`,
  `optuna_tuning_report.json`, `optuna_trial_ledger.csv`,
  `optuna_best_trial_trace.csv`, `optuna_tuned_predictions.csv`,
  `optuna_search_space_audit.csv`, `optuna_objective_audit.csv`,
  `optuna_tuning_serialized_spec.json`, fixed-budget `GridSampler` study на 6 trial'ов,
  validation-only `validation_logloss` objective, seed `1609`, best trial `4`
  (`depth=2`, `learning_rate=0.05`, `validation_logloss=0.696531`),
  no-test-objective gate, warning что cost gate все еще хуже baseline,
  readiness `ready_for_mlflow_lesson` и 10 behavioral tests;
- `16/10` — MLflow для истории экспериментов: завершен как
  `mlflow-experiment-ledger-exporter` с `mlflow_tracking_policy_spec.json`,
  `mlflow_experiment_report.json`, `mlflow_run_table.csv`,
  `mlflow_artifact_inventory.csv`, `mlflow_metric_history.csv`,
  `mlflow_reproducibility_checks.csv`, `mlflow_model_metadata.json`,
  `mlflow_tracking_serialized_spec.json`, локальными MLflow runs для
  source CatBoost, best Optuna trial и phase-15 baseline gate, stable `run_alias`
  вместо raw `run_id`, logged params/metrics/tags/artifacts, source package lineage,
  warning что cost gate все еще хуже baseline, local-file-store/registry boundary,
  readiness `ready_for_drift_and_stability_lesson` и 11 behavioral tests;
- `16/11` — drift, стабильность и interpretation package: завершен как
  `tabular-ml-interpretation-packager` с `tabular_ml_package_spec.json`,
  `tabular_ml_package.json`, `tabular_ml_package_report.json`,
  `tabular_ml_evidence_matrix.csv`, `score_drift.csv`, `feature_drift.csv`,
  `importance_stability.csv`, `segment_stability.csv`, `stability_report.json`,
  `interpretation_report.md`, `decision_report.md`,
  `tabular_ml_package_manifest.json`, upstream evidence matrix на 16 строк,
  score drift stable, feature drift watch по unseen `acquisition_channel`,
  disagreement watch по built-in/permutation/SHAP для `platform`, 13 hidden segment
  failure slices, decision status `keep_baseline`, monitoring status
  `drift_watch_required`, no-causal/no-serving boundary, sha256 manifest на 37 inputs
  и 10 generated outputs, 13 behavioral tests.

Runtime-зависимость `catboost` добавлена в уроке `16/01` как первая точка использования
реального CatBoost API; в `uv.lock` зафиксирована версия `1.2.10` (с `graphviz==0.21`).
Runtime-зависимость `shap` добавлена в уроке `16/06`; в `uv.lock` зафиксирована версия
`0.51.0`, потому что `0.52.0` требует Python `>=3.12`, а проект пока поддерживает
`>=3.11`. Runtime-зависимость `optuna` добавлена в уроке `16/09`; в `uv.lock`
зафиксирована версия `4.9.0`. Runtime-зависимость `mlflow-skinny` добавлена в уроке
`16/10`; в `uv.lock` зафиксирована версия `3.14.0`. Полный пакет `mlflow 3.14.0`
сейчас требует `pandas<3`, поэтому урок использует `mlflow-skinny` для Tracking API при
сохранении текущего `pandas>=3` контракта проекта. Runtime-зависимость `xlsxwriter`
добавлена в уроке `17/02`; в `uv.lock` зафиксирована версия `3.2.9`, а `openpyxl`
используется для audit/readback готового XLSX. Runtime-зависимость `streamlit` добавлена
в уроке `17/06`; в `uv.lock` зафиксирована версия `1.56.0`, потому что более ранние
версии Streamlit в lock resolution конфликтовали с текущим `pandas>=3` контрактом
проекта.

## Фаза 17

Фаза 17 спроектирована в `docs/phase-17-design.md`: она превращает verified evidence
package из любого маршрута в `stakeholder-delivery-package` с decision memo, workbook,
reproducible report, interactive appendix, Streamlit app, CLI/schedule, optional
FastAPI/Docker interfaces and support handoff. Границы фазы: это не повтор анализа, не
BI-платформа, не frontend/backend/DevOps-курс и не production ML monitoring.

Уроки `17/01`–`17/12` развернуты в `curriculum.json` как последовательность на 960 минут.
`17/01` завершен как `decision-memo-builder`: CLI собирает `executive_memo.md`,
`claim_evidence_matrix.csv`, `memo_audit.json` и `manifest.json` из `memo_spec.json`,
`evidence.csv` и `quality_gates.csv`, ловит invalid decision, uncited claims, unresolved
evidence, blocked quality/evidence и unsupported overclaim wording; 13 behavioral tests.
`17/02` завершен как `stakeholder-workbook-builder`: CLI собирает
`stakeholder_workbook.xlsx`, `workbook_audit.json`, `data_dictionary.csv` и `manifest.json`
из `workbook_spec.json`, `metric_summary.csv`, `claim_evidence_matrix.csv` и
`memo_audit.json`; workbook содержит `Summary`, `Metrics`, `Evidence`, `Data Dictionary`
и `Checks`, проверяет Excel tables, freeze panes, formula/cache reconciliation,
dictionary coverage, upstream memo validity и no-sensitive-columns policy; 14 behavioral
tests.
`17/03` завершен как `quarto-report-packager`: CLI собирает `_quarto.yml`, `params.yml`,
`report.qmd`, deterministic `report.html` preview, `figures/guardrail_status.svg`,
`source_links.csv`, `report_audit.json`, `rebuild_check.json` и `render_manifest.json`
из `report_spec.json`, `metric_summary.csv`, `claim_evidence_matrix.csv`,
`workbook_audit.json` и `memo_audit.json`; проверяет executable Python blocks,
parameters cell, Quarto render command, source links/checksums, upstream memo/workbook
validity, assumptions/limitations, no-sensitive-source-fields policy, required figures
и rebuild relative to previous manifest; 16 behavioral tests.
`17/04` завершен как `multi-format-report-renderer`: CLI собирает `report.html`,
`report.pdf`, `report.docx`, `format_targets.json`, `asset_inventory.csv`,
`link_audit.csv`, `format_qa_report.json` и `format_manifest.json` из Quarto report
package урока `17/03`; проверяет explicit HTML/PDF/DOCX targets, real Quarto render
commands, upstream report audit, source links/checksums, self-contained embedded HTML
figure resources, minimal valid PDF, valid DOCX OOXML package without external
relationships, figure traceability across targets, static fallback boundary для
interactive-only content, layout-sensitive warnings и rebuild relative to previous
format manifest; 19 behavioral tests.
`17/05` завершен как `plotly-interactive-appendix`: CLI собирает
`interactive_spec.json`, `interactive_appendix.html`, `plotly_figure_spec.json`,
`static-fallbacks/metric_status.svg`, `source_table_links.csv`,
`interaction_audit.json` и `interaction_manifest.json` из multi-format package урока
`17/04`; проверяет Plotly dropdown filters, hovertemplate/customdata, source table
links/checksums, upstream format QA/link audit, sensitive-field redaction, standalone
HTML export without Dash/CDN script, static fallback и rebuild relative to previous
interaction manifest; 19 behavioral tests.
`17/06` завершен как `streamlit-stakeholder-app`: CLI собирает `streamlit_app.py`,
`app_contract.json`, `app_data/metric_summary.csv`, `app_data/claim_evidence_matrix.csv`,
`app_data/plotly_figure_spec.json`, `app_data/static-fallbacks/metric_status.svg`,
`app_data/source_table_links.csv`, `app_data/interaction_audit.json`,
`app_data/interaction_manifest.json`, `filters_audit.json`, `download_manifest.json`,
`downloads/stakeholder_app_bundle.zip`, `app_audit.json`, `app_manifest.json` и
`app_runbook.md` из Plotly appendix урока `17/05`; проверяет required Streamlit API
markers, app contract views/filters/downloads, upstream interaction audit, filters/default
state, source table hash freshness, precomputed-only/no-network/no-secrets/no-cache
boundary, sanitized public download bundle, lineage hashes и sensitive-field redaction
в app data, zip и public audit; 21 behavioral test.
`17/07` завершен как `streamlit-cache-state-auditor`: CLI собирает enhanced
`streamlit_app.py`, `cache_state_contract.json`, `freshness_policy.json`,
`freshness_report.json`, `cache_state_audit.json`, `cache_state_manifest.json` и
`cache_state_runbook.md` поверх app bundle урока `17/06`; проверяет `st.cache_data` для
CSV/JSON data loaders, `st.cache_resource` для Plotly figure resource payload,
`st.session_state` для per-session filters/view/manual refresh/input digest, TTL и
max_entries policy, checksum-based invalidation, manual cache clear, freshness report,
stale warnings и disabled downloads, input digest drift, upstream app audit,
no-network/no-secrets/no-disk-persist-cache boundary и manifest hashes; 22 behavioral
tests.
`17/08` завершен как `delivery-cli-runner`: CLI оркестрирует cache/state-ready app package
урока `17/07` через явные `--app-dir`, `--cache-state-contract`, `--freshness-policy`,
`--cli-contract` и `--output-dir`, поддерживает `--check` без публикации, staged publish
через `TemporaryDirectory` и `os.replace`, `--overwrite` только после успешного staging
build, optional `--allow-freshness-warning`, JSON stdout/report, `cli_run_report.json`,
`cli_publish_manifest.json` и `delivery_cli_contract.json`; проверяет explicit input
paths, no implicit cwd inputs, check/publish modes, exit-code policy (`success=0`,
`data_quality_block=10`, `freshness_warning=20`, `system_error=30`, argparse usage `2`),
no partial publish on blockers, stale-only warning behavior, existing output protection,
publish manifest hashes and atomic strategy; 18 behavioral tests.
`17/09` завершен как `scheduled-delivery-workflow`: workflow-артефакт поверх CLI урока
`17/08` собирает `schedule_contract.json`, GitHub Actions style `schedule_workflow.yml`,
`run_history.csv`, `schedule_run_report.json`, `schedule_freshness_report.json`,
`last_success_marker.json`, `failure_notification_mock.json`,
`scheduled_publish_manifest.json`, `reports/latest_cli_run_report.json` и вложенный
`published-delivery/`; проверяет owner, UTC cron, default-branch/minimum-interval/top-of-hour
GitHub Actions caveats, `workflow_dispatch` recovery path, explicit CLI args, no source
mutation, no partial publish on failed runs, last-success update only on fresh success,
stale warning behavior, data-quality block preservation of previous package, notification
reason codes, run history и manifest hashes; 19 behavioral tests.
`17/10` завершен как `fastapi-delivery-endpoint`: app-артефакт поверх scheduled package
урока `17/09` генерирует `fastapi-delivery-api/` с `api.py`, `api_contract.json`,
`openapi_schema.json`, `api_contract_tests.json`, `api_audit.json`,
`api_manifest.json`, `cli_fallback.md` и copied `api_data/`; проверяет read-only GET
routes, Pydantic response models, OpenAPI paths/schemas, runtime validation через
`TestClient`, clear `404`/`422`, no mutation/network/env patterns, blocking for missing
run history или non-success upstream package, CLI `--write-example`/`--fail-on-invalid`,
manifest hashes и reproducible CLI fallback; 16 behavioral tests. Добавлены явные
зависимости `fastapi`, `uvicorn` и `httpx2` для запуска endpoint и contract tests.
`17/11` завершен как `docker-packaging-audit`: tool-артефакт поверх FastAPI package
урока `17/10` генерирует `docker-delivery-package/` с `Dockerfile`, `.dockerignore`,
`container_contract.json`, `docker_contract_tests.json`, `docker_build_context_report.json`,
`docker_run_manifest.json`, `docker_audit.json`, `docker_manifest.json`, `docker_runbook.md`
и copied `app/`; проверяет minimal build context, required `.dockerignore` patterns,
no-secret/no-cache/no-raw-data policy, pinned `python:3.12-slim`, non-root `USER appuser`,
запрет `COPY . .`/secret args/root runtime, local-only/no-registry-push boundary,
source secret candidates not copied, manifest equivalence с локальным `api_manifest.json`,
CLI `--write-example`/`--fail-on-invalid` и manifest hashes; 20 behavioral tests.
`17/12` завершен как `stakeholder-delivery-package`: tool-артефакт поверх всей цепочки
фазы 17 собирает финальный `stakeholder-delivery-package/` с `input/`, `memo/`,
`workbook/`, `report/`, `interactive/`, `app/`, `automation/`, `optional-api/`,
`optional-container/`, `handoff/` и root `manifest.json`; проверяет owner/backup,
cadence, rerun command, support policy, escalation path, retirement triggers,
allowed `decision_status`, upstream quality gates, freshness state, optional API/Docker
contracts, public no-secret policy, evidence index, runbook, changelog, stakeholder
email и SHA-256 manifest для всех файлов; 18 behavioral tests.
Фаза 17 полностью завершена.

## Фаза 18

Фаза 18 спроектирована в `docs/phase-18-design.md` как один stage-gated capstone workflow
на 2640 минут, или 44 часа. Студент выбирает один из шести маршрутов: core analytics,
product/experiments, data/analytics engineering, decision science, machine learning или
delivery product. Все маршруты используют общие gates для decision framing, data
contract, baseline, reproducible implementation, independent verification, peer review
и defense, но сохраняют собственные пререквизиты и claim boundaries.

Уроки `18/01`–`18/07` развернуты в `curriculum.json`. Итоговый
`capstone-portfolio-package` обязан собираться одной командой, содержать shadow
calculation, minimum three negative fixtures, sensitivity check, evidence ledger,
review/response history, assistance disclosure и SHA-256 manifest. Приемка использует
critical blockers и общую rubric из шести измерений; presentation quality не может
компенсировать неверный grain, неподтвержденный claim или невоспроизводимый результат.

`18/01` завершен как `capstone-brief-validator`: standalone CLI проверяет decision owner,
decision options с обязательным `no_action`, шесть route profiles и variant-specific
prerequisites, claim boundary, decision unit/population/horizon, scope 30-50 часов,
testable success criteria, risk coverage по data access/privacy/methodology/compute/
delivery/review, семь milestones на 44 часа и assistance disclosure; выпускает
`capstone_brief_audit.json`, `risk_register.csv`, `milestone_plan.csv`,
`capstone_state.json` и `brief_manifest.json`, оставляя reference tiny profile валидным с
явным warning `reference_profile_is_not_portfolio_evidence`; 20 behavioral tests.

`18/02` завершен как `capstone-data-contract-auditor`: standalone CLI продолжает
checksum-verified brief package и проверяет dataset manifest против фактических bytes,
schema/types/nullability, grain и non-null unique keys, many-to-one relationships и
orphans, freshness и complete observation windows, source owner/origin/license/allowed
uses/reproducibility, known defects, privacy policy и route-specific leakage/quality
controls для восьми route/variant profiles. Пакет выпускает `data_contract.json`,
`dataset_manifest.json`, `data_audit.json`, `lineage_report.csv`,
`checksum_inventory.csv`, агрегированный `public_data_sample.csv`, обновленный
`capstone_state.json` и SHA-256 `data_package_manifest.json`; raw row-level sources не
копируются, reference profile получает `data_ready`; 20 behavioral tests.

`18/03` завершен как `capstone-baseline-gate`: standalone CLI продолжает
checksum-verified data package и строит простейший route-specific decision baseline на
агрегированном public sample. Reference core rule ранжирует сегменты по observed churn
rate с deterministic support-load tie-break, выбирает `high_touch`, фиксирует
`captured_churn_recall=0.666667` при capacity четыре пользователя и не заявляет causal
effect. Gate независимо сверяет четыре counts и три rates на tiny slice, замораживает
practical threshold `0.766667`, tolerance и capacity до candidate result, ограничивает
dependencies/runtime/config/12-hour implementation budget и сохраняет retain-baseline
stop rule. Пакет выпускает `baseline_spec.json`, `baseline_report.json`,
`baseline_metrics.csv`, `baseline_decision.json`, `manual_reconciliation.csv`,
`acceptance_gate.json`, `complexity_budget.json`, обновленный `capstone_state.json` и
SHA-256 `baseline_manifest.json` с `candidate_results_observed=false`; 22 behavioral
tests.

`18/04` завершен как `capstone-route-implementation`: standalone CLI продолжает
checksum-verified baseline package, проверяет immutable upstream contracts и исполняет
один из восьми route/variant adapter profiles через общий package interface. Reference
core adapter ранжирует сегменты по frozen weighted score из churn, activation и support
load: `high_touch` получает score `1.0`, но candidate сохраняет
`captured_churn_recall=0.666667` при practical threshold `0.766667`, поэтому честно
остается выбранным baseline. Пакет фиксирует predeclared config и complexity/environment
budget, выпускает `implementation_report.json`, `implementation_config.json`,
`route_adapter_report.json`, candidate metrics/decision/acceptance, `evidence_ledger.csv`,
ordered `run_trace.csv`, обновленный `capstone_state.json` и SHA-256
`implementation_manifest.json` с locked environment, `raw_sources_copied=false` и
`upstream_inputs_mutated=false`; 26 behavioral tests.

`18/05` завершен как `capstone-independent-verifier`: standalone CLI принимает immutable
implementation и baseline packages, pinned implementation runner и predeclared
verification spec. Harness повторяет implementation в isolated temporary repository и
сравнивает десять outputs и manifest по SHA-256, а отдельный standard-library shadow
oracle независимо пересчитывает components, ranking, denominator, capacity и frozen
acceptance gate. Reference result подтверждает `candidate_value=0.666667` и сохраняет
baseline; четыре negative fixtures ловят checksum tampering, rehashed stale state,
измененный denominator и несуществующее evidence field. Пакет также выпускает пять
threshold/capacity sensitivity scenarios с честным decision flip при threshold `-0.1`,
claim-evidence audit, route controls, test/skip/xfail inventory, обновленный
`capstone_state.json` и deterministic SHA-256 `verification_manifest.json`; 29 behavioral
tests.

`18/06` завершен как `capstone-peer-review-kit`: standalone CLI принимает immutable
verification package, predeclared review spec и review submission, проверяет self-review,
independent reviewer identity/conflict/clean-context disclosure и exact reviewed manifest.
Reference reviewer создает один `major`, один `minor` и один `question` с точными evidence
selectors; author response ledger использует только `accepted`, `partially_accepted` и
`declined_with_evidence`, а logical changed scopes получают before/after SHA-256 и
predeclared affected-check mapping. Re-review независимо повторяет sensitivity,
claim-evidence и clean-room summary checks, запрещает author-declared `resolved`, закрывает
все три findings и выпускает provisional rubric `19/24`, `review_ready` state и
deterministic `review_manifest.json`, не заявляя final defense result; 29 behavioral tests.

`18/07` завершен как `capstone-portfolio-builder`: standalone CLI проверяет immutable
package chain шести предыдущих стадий и exact reviewed manifest, предобъявленный defense
spec, независимость evaluator, восьмисекционный brief до десяти минут, bounded claims и
минимум три класса challenge questions. Live demo запускает implementation в temporary
directory и пофайлово сравнивает outputs с reviewed manifest; финальный package сохраняет
stage provenance, public aggregate sample, runbook, limitations, assistance disclosure,
decision report, root SHA-256 manifest и verify mode. Critical blockers применяются до
rubric; reference result получает `passed`, `21/24`, пять challenge classes и exact live
rerun, но не distinction. Provenance ловит подмену даже после root rehash, public scan
блокирует fake secret/PII markers; 26 behavioral tests.

Все 19 фаз и 198 уроков завершены. Следующий содержательный шаг — релизная приемка,
публикация сайта и выбор первого post-release улучшения по обратной связи.

## Уже принятые решения

- Один курс с маршрутами, а не несколько независимых курсов.
- Общее ядро — фазы 00–07.
- Задача и модель данных появляются раньше библиотеки.
- Надежность, тесты и воспроизводимость вводятся с первых фаз.
- `uv` выбран основным менеджером окружений вместо Conda.
- Библиотеки курса фиксируются на актуальных стабильных версиях в `uv.lock`;
  обновление делается отдельным осознанным diff, без pre-release по умолчанию.
- SQL, продуктовая аналитика, эксперименты, analytics engineering и доставка результата
  являются самостоятельными фазами, а не приложениями к pandas или ML.
- FastAPI и Docker остаются факультативными способами доставки, а не обязательным финалом
  для каждого аналитика.
- `curriculum.json` — источник правды; дорожная карта, страницы фаз и данные сайта
  генерируются.
- Сайт публикует каждый урок как заранее сгенерированную статическую HTML-страницу;
  GitHub остаётся вторичным источником истории и обратной связи, а не местом чтения.
- Форма практики определяется результатом обучения: `executable` проверяется кодом и
  behavioral tests, `guided-artifact` — самостоятельным артефактом и отдельной рубрикой.
  Тип урока `learn`/`build`/`case` не диктует наличие кода.

## Неопределенности

- Публичный сайт размещён на `datascience.xyz`; после каждого релиза требуется проверить,
  что внешний hosting получил актуальное содержимое `site/`.
- Аналитика посещений не выбрана.
- Состав факультативов может уточняться при разработке соответствующих фаз, но изменение
  не должно ломать пререквизиты основных маршрутов.

## Полная проверка

Последний полный прогон после переработки начала курса: `uv run --locked python
scripts/run_lesson_tests.py` завершился успешно, `Completed lesson test suites: 196;
rubric-verified lessons: 1`. Локально также пройдены 46 root tests и все
structural/render checks:
`uv run --locked python scripts/validate_course.py`,
`uv run --locked python scripts/render_curriculum.py --check`,
`uv run --locked python scripts/render_outputs.py --check`,
`uv run --locked python scripts/render_site.py --check` и
`uv run --locked python -m unittest discover -s tests`.

```bash
uv sync --locked --dev
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```
