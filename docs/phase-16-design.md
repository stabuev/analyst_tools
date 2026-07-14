# Проект фазы 16: Табличный ML и интерпретация

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую задачу, роли инструментов и контракт итогового
`tabular-ml-interpretation-package`.

## Результат фазы

Студент берет честный `ml-baseline-package` из фазы 15 и улучшает его сильной табличной
моделью без потери контроля над постановкой, split protocol, метриками, threshold policy,
калибровкой, segment errors и ограничениями. Фаза учит не "получить CatBoost score", а
защитить решение от типичных ошибок продвинутого табличного ML:

1. **Stronger model contract:** CatBoost-кандидат сравнивается с baseline на тех же rows,
   split roles, metric policy и threshold policy.
2. **Categorical feature contract:** категориальные признаки передаются нативно или
   кодируются только с train-fitted state, без target leakage и без silent category drift.
3. **Training control:** iteration budget, early stopping, validation curve и best
   iteration объясняются как часть protocol, а не как магическое ускорение.
4. **Interpretation stack:** встроенная важность, permutation importance и SHAP отвечают
   на разные вопросы и не подменяют друг друга.
5. **Decision layer:** threshold/cost/segment analysis проверяют, помогает ли улучшенная
   модель именно бизнес-решению с ограниченным budget.
6. **Experiment governance:** Optuna и MLflow используются как воспроизводимый журнал
   кандидатов, а не как AutoML-замена методологии.
7. **Stability gate:** финальный package блокирует слишком сильный claim, если модель,
   объяснения, сегменты или drift diagnostics нестабильны.

Фаза состоит из пяти блоков:

1. `16/01`-`16/03`: CatBoost baseline, categorical features и early stopping.
2. `16/04`-`16/06`: built-in importance, permutation importance и SHAP.
3. `16/07`-`16/08`: segment-level interpretation и cost-sensitive threshold decisions.
4. `16/09`-`16/10`: Optuna tuning protocol и MLflow experiment ledger.
5. `16/11`: drift/stability audit и итоговый `tabular-ml-interpretation-package`.

Суммарная длительность - 900 минут, или 15 часов.

## Границы содержания

- **Не повтор фазы 15.** Problem spec, split manifest, preprocessing contract,
  calibration, leakage audit, model card и baseline package считаются входом. Здесь они
  расширяются сильной моделью и interpretation evidence.
- **Не соревнование библиотек.** Фаза выбирает CatBoost как один production-grade
  табличный boosting baseline. XGBoost/LightGBM не входят в обязательную траекторию,
  чтобы не превратить курс в leaderboard обзор.
- **Не AutoML.** Optuna ограничивается заранее объявленным search space, fixed budget,
  validation-only objective и audit trail. Скрытый feature search, blind hundreds of
  trials и test-driven tuning считаются failure modes.
- **Не causal inference.** SHAP, importance и segment effects объясняют поведение модели,
  а не эффект удерживающего предложения. Causal claims остаются фазе 13.
- **Не полноценный fairness курс.** Slice metrics и segment stability обязательны, но
  правовые рамки, bias mitigation и fairness methodology не являются целью фазы.
- **Не production monitoring.** Drift and stability здесь локальные: train/validation/test
  period shift, score distribution, feature distribution, explanation stability. Online
  monitoring, scheduled scoring, API and dashboard delivery остаются фазе 17.
- **Не deep learning.** Embeddings, neural tabular models, GPU-first training и
  transformers вне обязательного курса.
- **Не MLOps-платформа.** MLflow используется локально для run history and artifacts.
  Registry, remote tracking server, ACL, deployment and model lifecycle governance
  остаются вне фазы.

## Роли инструментов

Новые зависимости не добавляются на этапе проектирования. CatBoost, SHAP, Optuna и MLflow
добавляются только в уроках, где впервые нужен реальный API. При разработке конкретного
урока версии сверяются с `uv.lock`.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pandas / NumPy | Подготовка локальных audit tables, metric deltas, score distributions, PSI-style bins, stability checks | Новый обзор DataFrame API |
| DuckDB | Независимые checks по grain, split roles, feature availability и reconciliation experiment logs | Feature store или production warehouse |
| Pandera / Pydantic | Machine-readable specs для CatBoost run, categorical contract, tuning budget, explanation report и final package | Enterprise model governance |
| scikit-learn | Baseline comparison, metrics/scoring, permutation importance, calibration/threshold handoff | Повтор Pipeline/ColumnTransformer |
| CatBoost | Strong tabular classifier, native categorical handling, eval_set, early stopping, built-in feature importance, model metadata | Ranking, text features, GPU tuning, Spark |
| SHAP | TreeExplainer для CatBoost, local/global explanations, additivity checks, background choice audit | Обещание причинности или fairness guarantees |
| Optuna | Fixed-budget hyperparameter study, trial ledger, pruner/sampler trace, validation-only objective | AutoML, distributed optimization, hidden search |
| MLflow | Local experiment tracking, params/metrics/artifacts/model logging, run comparison export | Remote tracking server, registry, serving |
| Matplotlib / Seaborn / Plotly / Altair | Importance, SHAP summary, segment and drift panels | Новый dashboard курс |
| pytest | Behavioral tests для model comparison, categorical leakage, early stopping, explanations, tuning and final package | Нагрузочные тесты ML платформы |

Проверенные 3 июля 2026 года официальные и первичные ориентиры:

- [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier) -
  официальный Python API классификатора, включая sklearn-compatible estimator, параметры,
  атрибуты `best_iteration_`, `feature_importances_` и методы `predict_proba`,
  `get_feature_importance`.
- [CatBoost fit](https://catboost.ai/docs/en/concepts/python-reference_catboost_fit) -
  `eval_set`, `use_best_model`, overfitting detector и validation-driven best iteration.
- [CatBoost Pool](https://catboost.ai/docs/en/concepts/python-reference_pool) -
  контракт передачи `cat_features` по индексам или именам.
- [CatBoost feature importance](https://catboost.ai/docs/en/concepts/fstr) - типы
  feature strength и ограничения отдельных методов.
- [scikit-learn permutation importance](https://scikit-learn.org/stable/modules/permutation_importance.html) -
  модель-агностичная importance на held-out data, зависимость от scoring и предупреждения
  про плохие модели, MDI bias и correlated features.
- [SHAP TreeExplainer](https://shap.readthedocs.io/en/stable/generated/shap.TreeExplainer.html) -
  Tree SHAP для CatBoost/tree ensembles, `feature_perturbation`, background data,
  `model_output` и additivity.
- [Lundberg and Lee, A Unified Approach to Interpreting Model Predictions](https://arxiv.org/abs/1705.07874) -
  первичный источник по SHAP/Shapley additive explanations.
- [Optuna first optimization tutorial](https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/001_first.html) -
  objective, trial, study и `study.optimize`.
- [Optuna create_study](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.create_study.html) -
  storage, sampler, pruner, direction и persistence boundary.
- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) - runs, experiments,
  params, metrics, artifacts, local `mlruns` default и search.
- [MLflow CatBoost flavor](https://mlflow.org/docs/latest/python_api/mlflow.catboost.html) -
  logging/loading CatBoost models as native and pyfunc flavors.

## Единая задача и данные

Фаза продолжает вымышленный подписочный сервис и задачу из фазы 15: "за 7 дней до
окончания trial определить пользователей с высоким риском churn, чтобы команда поддержки
могла отправить ограниченное число удерживающих предложений".

Входом считается пакет `15/15`:

```text
ml-baseline-package/
├── problem_spec.json
├── split_manifest.csv
├── feature_availability_report.csv
├── leakage_report.json
├── calibration_report.json
├── segment-error-analysis.csv
├── model_card.md
└── manifest.json
```

Фаза 16 расширяет данные теми же `snapshot_id`, `user_id`, `prediction_time`,
`split_role`, `churned_14d`, но добавляет табличные признаки, где CatBoost и
интерпретация действительно нужны:

| Поле | Тип | Учебный смысл |
|---|---|---|
| `acquisition_channel` | categorical | Нативная категория с умеренной кардинальностью |
| `campaign_id` | high-cardinality categorical | Риск target encoding leakage и unstable importance |
| `support_topic_last_30d` | categorical with missing semantics | Missing как смысловая категория, а не zero |
| `device_model_family` | high-cardinality categorical | Drift по новым категориям |
| `merchant_category_top` | categorical | Связь с orders/events и risk of join duplication |
| `country` / `platform` / `plan_tier` | segment fields | Slice performance, threshold and stability |
| `days_to_trial_end`, `sessions_7d`, `orders_30d`, `support_tickets_14d` | numeric | Сравнение numeric vs categorical importance |
| `feature_available_at` | timestamp | Блокировка future information |

Профили:

- `tiny`: десятки rows с ручными expected values для model comparison, categorical
  inventory, early stopping trace, importance deltas, SHAP additivity, threshold impact и
  drift checks.
- `sample`: детерминированная локальная генерация сотен/тысяч rows для CatBoost,
  permutation importance, SHAP sampling, Optuna trials и MLflow ledger.
- Дефектные fixtures: high-cardinality target leakage, category seen only after
  prediction time, no validation set for early stopping, test-tuned threshold, unstable
  feature importance, correlated-feature importance trap, missing MLflow artifacts and
  drifted score distribution.

## Контракт tabular model spec

Каждый урок опирается на machine-readable spec:

```text
problem_id
baseline_package_id
model_family
model_id
candidate_role
prediction_unit
target_name
split_policy
metric_policy
threshold_policy
calibration_policy
categorical_feature_policy
feature_availability_policy
catboost_params
training_budget
early_stopping_policy
comparison_policy
importance_policy
shap_policy
segment_policy
cost_policy
tuning_policy
experiment_tracking_policy
drift_policy
stability_policy
decision_policy
known_limitations
rerun_instructions
```

Spec запрещает "улучшить модель пока score не понравится". Любое улучшение должно быть
связано с заранее объявленным validation objective, cost policy, comparison set,
interpretation scope и final decision status.

## Контракт отдельных методов

### CatBoost baseline

- CatBoost candidate обучается на тех же train rows and target, что baseline package.
- Validation/test roles не меняются ради нового estimator.
- `cat_features` задаются явно по именам или индексам и совпадают с feature contract.
- Модель сравнивается с dummy, linear, random forest baseline and previous selected model.
- Improvement claim требует validation evidence and test-only final check without
  selection.

### Categorical features

- High-cardinality categories не получают target statistics из validation/test.
- Unknown categories and missing categories имеют явный policy.
- Category inventory хранит train/validation/test coverage, new-category rate and rare
  category bins.
- Любая aggregate/category feature имеет `available_at <= prediction_time`.

### Early stopping

- `eval_set` строится только из validation rows.
- `best_iteration` and `tree_count` фиксируются в training trace.
- Test set не участвует в overfitting detector, best iteration selection or tuning.
- Early stopping считается reproducibility feature only if random seed, metric and
  eval_set are stable.

### Importance and explanations

- Built-in importance маркируется как model-internal diagnostic, not causal effect.
- Permutation importance считается на held-out validation/test-like slice with declared
  scoring and repeats.
- Correlated features and high-cardinality bias produce warnings.
- SHAP report фиксирует background choice, output space, expected value, additivity check,
  local rows, global summary and explanation limitations.
- Explanation disagreement не скрывается: если built-in, permutation and SHAP disagree,
  package показывает disagreement table.

### Segment, threshold and cost

- Segment analysis использует calibrated/declared score, threshold policy and business
  cost from problem spec.
- Улучшение average metric не считается достаточным, если model worsens critical segment
  beyond allowed tolerance.
- Threshold выбирается на validation, test only verifies.
- Decision report отделяет "rank users for review" from "prove retention offer effect".

### Optuna and MLflow

- Search space, objective, metric direction, trial budget and seed фиксируются до запуска.
- Optuna storage/log export сохраняет all trials, not only best params.
- Nested CV or validation-only objective selected explicitly; test is invisible.
- MLflow run ledger logs params, metrics, artifacts, model metadata and source package id.
- Missing artifacts or inconsistent run tags block final package.

### Drift and stability

- Stability checks compare train/validation/test or historical scoring windows.
- Feature distribution, score distribution, top-k overlap, importance rank and SHAP
  summary stability are separate diagnostics.
- Drift warning does not automatically mean model is bad; it changes decision status and
  required monitoring/retraining notes.

## Интеграционный мини-проект

`16/11` собирает поставку:

```text
tabular-ml-interpretation-package/
├── input/
│   ├── baseline-package-manifest.json
│   ├── problem-spec.json
│   ├── split-manifest.csv
│   └── feature-contract.json
├── model/
│   ├── catboost-model-spec.json
│   ├── training-trace.json
│   ├── model-comparison.csv
│   ├── calibrated-scores.csv
│   └── threshold-decision.csv
├── categorical/
│   ├── category-inventory.csv
│   ├── category-leakage-audit.csv
│   └── unknown-category-policy.json
├── interpretation/
│   ├── built-in-importance.csv
│   ├── permutation-importance.csv
│   ├── shap-values-sample.parquet
│   ├── shap-summary.csv
│   ├── explanation-disagreement.csv
│   └── interpretation-report.md
├── experiments/
│   ├── optuna-study-summary.json
│   ├── optuna-trials.csv
│   ├── mlflow-run-ledger.csv
│   └── experiment-selection-audit.json
├── stability/
│   ├── segment-stability.csv
│   ├── score-drift.csv
│   ├── feature-drift.csv
│   ├── importance-stability.csv
│   └── stability-report.json
├── decision-report.md
└── manifest.json
```

Пакет обязан:

- ссылаться на upstream `ml-baseline-package` and checksum manifest;
- сохранять problem/split/metric/threshold/calibration policies без silent mutation;
- сравнивать CatBoost candidate with baseline on identical evaluation rows;
- хранить categorical feature contract and leakage audit;
- публиковать training trace with best iteration, eval metric and random seed;
- показывать at least three explanation views: built-in, permutation and SHAP;
- объяснять disagreement and limitations of explanations;
- проверять segment performance, cost-sensitive threshold and top-k decision impact;
- сохранять Optuna/MLflow evidence for all candidate runs;
- проверять feature/score/importance/explanation stability;
- ограничивать decision statement одним из статусов:
  `promote_candidate_with_limits`, `keep_baseline`, `needs_more_data`,
  `leakage_blocked`, `unstable_explanations`, `drift_watch_required`,
  `inconclusive`;
- выпускать SHA-256 manifest всех входных и generated файлов.

## Проверяемость

- CatBoost tests проверяют identical split roles, explicit `cat_features`, deterministic
  seed, model comparison and no test-driven selection.
- Categorical tests ловят target leakage, post-prediction categories, high-cardinality
  instability, missing-as-zero and unknown category policy gaps.
- Early-stopping tests проверяют validation-only `eval_set`, best iteration trace,
  changed tree count and missing validation block.
- Built-in importance tests проверяют method label, feature names, high-cardinality
  warnings and no causal wording.
- Permutation tests проверяют held-out data, scoring, repeats, random seed, confidence
  bands and correlated-feature warning.
- SHAP tests проверяют output space, background sample, additivity, expected value,
  local row evidence and explanation limitation text.
- Segment/cost tests проверяют segment-level metric deltas, small-n warnings,
  validation-only threshold and budget impact.
- Optuna tests проверяют fixed search space, trial budget, direction, storage export,
  best-trial selection and no test objective.
- MLflow tests проверяют run ledger, params/metrics/artifacts/model metadata and missing
  artifact block.
- Final package tests проверяют structure, manifest, upstream checksums,
  interpretation-to-evidence links, stability diagnostics, decision status and no causal
  or production-serving overclaim.
