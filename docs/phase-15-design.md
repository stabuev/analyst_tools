# Проект фазы 15: Прикладное машинное обучение

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую supervised ML-задачу, модель данных, роли инструментов и контракт итогового
`ml-baseline-package`.

## Результат фазы

Студент превращает бизнес-задачу в проверяемую supervised ML-постановку и выпускает
воспроизводимый baseline, которому можно верить больше, чем красивому notebook score.
Он сначала фиксирует decision, prediction unit, target, prediction time, horizon,
negative class, allowed features и forbidden future information, затем строит честный
split, простые baselines, preprocessing pipeline, модели-кандидаты, cross-validation,
calibration, error analysis и model card.

Фаза учит держать раздельно шесть слоев:

1. **ML-постановка:** что именно предсказываем, для какого решения и когда prediction
   будет доступен.
2. **Data contract:** одна строка = одна prediction unit, target измеряется после
   prediction time, features доступны до prediction time.
3. **Evaluation protocol:** train/validation/test, segment slices, imbalance policy и
   метрики привязаны к business cost.
4. **Pipeline:** preprocessing, imputation, encoding, scaling и estimator обучаются
   только на train внутри одного воспроизводимого объекта.
5. **Model comparison:** сложная модель должна победить dumb и linear baselines на
   заранее выбранной метрике и не развалиться на сегментах.
6. **Model card:** итоговая поставка говорит intended use, limitations, metrics,
   calibration, error slices, leakage checks и decision threshold.

Фаза состоит из пяти блоков:

1. `15/01`-`15/03`: ML problem framing, split protocol и метрики/стоимость ошибки.
2. `15/04`-`15/06`: preprocessing as model, `Pipeline` и `ColumnTransformer`.
3. `15/07`-`15/10`: linear baseline, decision tree, tree ensembles и cross-validation.
4. `15/11`-`15/14`: imbalance, probability calibration, data leakage и segment error
   analysis.
5. `15/15`: итоговый `ml-baseline-package` и model card.

Суммарная длительность - 1170 минут, или 19,5 часа.

Это явно согласованное исключение из обычного ориентира 10-18 часов. Фаза остается
единой, потому что все 15 уроков последовательно собирают один проверяемый
`ml-baseline-package`: искусственное разбиение отделило бы model card и leakage/error
evidence от постановки, split и pipeline, на которых они основаны. Темы сильного
табличного ML и интерпретации при этом вынесены в отдельную фазу 16.

## Границы содержания

- **Не повтор статистики.** Bias/variance, intervals, bootstrap, regression diagnostics и
  hypothesis tests уже есть в фазе 09. Здесь они применяются к supervised ML evaluation,
  calibration и threshold decisions.
- **Не causal inference.** Model performance не доказывает effect of intervention.
  Uplift, treatment effect, DiD/RDD/IV и sensitivity остаются фазе 13.
- **Не forecasting.** Time-aware splits и leakage checks переиспользуют идеи фазы 14, но
  прогнозирование временных рядов, ETS/ARIMA и forecast intervals не повторяются.
- **Не deep learning.** Нейросети, embeddings, transformers и GPU-training не входят в
  обязательную фазу: табличный supervised ML закрывается понятными baselines.
- **Не AutoML.** Автоматический перебор сотен моделей, hidden feature search и blind
  hyperparameter tuning считаются failure mode.
- **Не production serving.** Persistence, API, batch scoring, monitoring, drift dashboard
  и scheduled runs относятся к фазе 17 или к будущим факультативам.
- **Не fairness курс.** Segment analysis и model card требуют slice metrics и limitations,
  но полноценная fairness methodology, правовые рамки и bias mitigation остаются вне
  обязательного курса.
- **Не интерпретация сильных моделей.** CatBoost, SHAP, permutation importance, Optuna и
  MLflow запланированы в фазе 16 или delivery, а не в базовой ML-фазе.

## Роли инструментов

Новые зависимости не добавляются на этапе проектирования. Фаза в итоге потребует
`scikit-learn`, но dependency добавляется в уроке, где впервые нужен реальный sklearn API,
а не раньше. Уже доступные pandas, NumPy, SciPy, statsmodels, DuckDB, Pandera/Pydantic и
pytest покрывают problem framing, tiny data generation, ручные baselines, split audits и
контракты.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pandas | Сбор supervised learning table, feature availability audit, segment slices, error tables | Новый обзор pandas |
| NumPy | Ручные dummy baselines, confusion matrix, threshold sweep, reproducible sampling | Полный numerical ML с нуля |
| SciPy / statsmodels | Проверки распределений, confidence-style diagnostics для slice uncertainty, logistic baseline cross-check при необходимости | Causal или econometric modeling |
| DuckDB | Независимые grain/leakage/split checks и reconciliation таблиц | Feature store и warehouse orchestration |
| Pandera / Pydantic | Контракты problem spec, split policy, feature spec, metric policy и model card schema | Enterprise model governance |
| scikit-learn | `train_test_split`, `Dummy*`, metrics/scoring, `Pipeline`, `ColumnTransformer`, linear models, trees, ensembles, CV и calibration | AutoML, deep learning, distributed training |
| Matplotlib / Seaborn / Plotly / Altair | Error analysis, calibration curves, threshold tradeoff, segment diagnostics | Новый dashboard курс |
| pytest | Behavioral tests для framing, splits, metrics, leakage, pipeline reproducibility и final package | Повтор основ тестирования |

Проверенные на 1 июля 2026 года официальные и первичные ориентиры:

- [scikit-learn: Model selection and evaluation](https://scikit-learn.org/stable/model_selection.html) -
  официальный раздел по cross-validation, hyperparameter tuning, decision threshold,
  metrics/scoring и validation curves.
- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) -
  официальный разбор inconsistent preprocessing и leakage; особенно важны правила
  "split first" и "never fit on test".
- [scikit-learn: Pipeline](https://scikit-learn.org/stable/modules/generated/sklearn.pipeline.Pipeline.html) -
  API composite estimator, который связывает preprocessing и estimator в один объект.
- [scikit-learn: ColumnTransformer](https://scikit-learn.org/stable/modules/generated/sklearn.compose.ColumnTransformer.html) -
  API для разных трансформаций по числовым, категориальным и бинарным колонкам.
- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) -
  официальный раздел по calibration curves и calibrated classifiers.
- [Mitchell et al., Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993) -
  первичный источник по model cards: intended use, evaluation conditions, limitations и
  subgroup performance.

При разработке конкретного урока API и версии необходимо сверять с фактически
зафиксированным `uv.lock`, а не только с online-документацией.

## Единая ML-задача и данные

Фаза использует тот же вымышленный подписочный сервис с маркетплейсом. Рабочая задача:
«За 7 дней до окончания trial определить пользователей с высоким риском churn, чтобы
команда поддержки могла отправить ограниченное число удерживающих предложений».

Почему это хорошая учебная ML-задача:

- prediction unit естественна: один пользователь на дату скоринга;
- target имеет horizon: churn в течение 14 дней после prediction time;
- decision имеет стоимость: false positive тратит offer budget, false negative теряет
  подписку;
- есть class imbalance и разные segment-level риски;
- features приходят из событий, заказов, поддержки, подписки и календаря;
- много leakage ловушек: future activity, cancellation events, post-offer outcomes,
  full-sample preprocessing, target leakage в агрегатах и random split по строкам одного
  пользователя.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `ml_users` | один пользователь | `user_id` |
| `ml_subscriptions` | один период подписки | `subscription_id` |
| `ml_events` | одно событие клиента | `event_id` |
| `ml_orders` | один заказ | `order_id` |
| `ml_support_tickets` | одно обращение | `ticket_id` |
| `ml_scoring_snapshots` | один пользователь и одна дата скоринга | `snapshot_id` |
| `ml_labels` | один snapshot и target horizon | `snapshot_id` |
| `ml_feature_table` | один snapshot после feature build | `snapshot_id` |

Ключевые поля `ml_scoring_snapshots`:

| Поле | Смысл |
|---|---|
| `snapshot_id` | стабильный ключ prediction row |
| `user_id` | пользователь, для которого делается prediction |
| `prediction_time` | момент, в который модель должна быть применима |
| `trial_end_at` | конец trial или текущего периода подписки |
| `segment_id` | платформа, страна или план для slice metrics |
| `eligible_for_offer` | бизнес-правило eligibility до prediction |
| `split_group` | precomputed cohort/time group для deterministic split |

Ключевые поля `ml_labels`:

| Поле | Смысл |
|---|---|
| `snapshot_id` | связь с prediction row |
| `target_name` | например `churn_14d` |
| `label_observed_at` | когда target стал известен |
| `churned_14d` | бинарный target |
| `label_window_complete` | можно ли использовать label для training/evaluation |

Профили данных:

- `tiny`: десятки snapshot rows с ручными expected values для framing, split, metrics,
  baseline, leakage cases и model card.
- `sample`: детерминированная локальная генерация тысяч пользователей и snapshot rows
  для pipeline, CV, calibration и segment error analysis.
- Дефектные fixtures: минимальные мутации valid baseline для одного failure mode.

Заложенные свойства и failure modes:

- target определен после prediction time или вообще не имеет horizon;
- одна prediction row размножается JOIN-ом к events/orders/support tickets;
- random row split кладет одного пользователя в train и test;
- preprocessing `fit` делается до split;
- `days_since_last_event` использует события после prediction time;
- categorical level встречается только в test;
- missing value silently превращается в zero и меняет смысл;
- majority-class baseline выглядит высоким по accuracy на imbalanced target;
- ROC AUC выглядит прилично, но precision@budget непригоден для решения;
- tree model переобучается и выигрывает train, но проигрывает validation;
- CV folds пересекаются по user/time cohort;
- probability scores не калиброваны и ломают threshold decision;
- leakage feature выбирается на validation score;
- aggregate score скрывает Android/low-activity segment failure;
- model card делает claim шире, чем evidence.

## Контракт ML problem spec

Каждый урок работает через machine-readable problem spec:

```text
problem_id
business_decision
prediction_unit
target_name
target_definition
positive_class
negative_class
prediction_time
label_window
eligible_population
decision_action
decision_budget
business_costs
allowed_feature_sources
forbidden_feature_sources
split_policy
baseline_policy
metric_policy
threshold_policy
calibration_policy
segment_policy
model_card_policy
known_limitations
rerun_instructions
```

Spec запрещает "предсказать churn вообще". Если prediction time, target horizon,
eligible population, negative class, feature availability и decision cost не зафиксированы
до model evaluation, такая ML-задача не готова к обучению.

## Контракт отдельных методов

### Problem framing

- одна строка training/evaluation table соответствует prediction unit;
- target измеряется после prediction time, features - до prediction time;
- positive и negative class имеют бизнес-смысл;
- prediction не является causal claim о действии предложения;
- baseline, split, metric и threshold policy существуют до fit.

### Splits

- split делается до preprocessing и feature selection;
- один пользователь/cohort не пересекается между train/validation/test, если это
  нарушает независимость оценки;
- temporal или group split выбирается по production use case;
- validation используется для выбора threshold/model, test - только для финальной оценки.

### Метрики и threshold

- metric policy связывает confusion matrix с business cost;
- accuracy не может быть primary metric при сильном imbalance;
- precision/recall/FPR/FNR, ROC AUC, PR AUC и log loss имеют разные decision roles;
- threshold выбирается на validation по заранее заданному budget/cost rule.

### Preprocessing, Pipeline, ColumnTransformer

- imputation, scaling, encoding и feature selection обучаются только на train;
- unknown categories имеют явную policy;
- raw feature table и transformed feature matrix имеют проверяемую lineage;
- pipeline сохраняет одинаковую трансформацию для train/validation/test.

### Baselines and models

- `DummyClassifier`/manual majority/random-prior baseline обязателен;
- linear model - первый обучаемый baseline с интерпретируемым направлением признаков;
- tree - диагностирует non-linear rules, но контролируется depth/min samples;
- ensemble - улучшает stability, но не отменяет error analysis и model card;
- candidate model must beat simple baseline на chosen metric and slices.

### Cross-validation и leakage

- CV folds должны уважать group/time constraints;
- hyperparameter search не видит test;
- feature selection inside CV, not before CV;
- leakage audit проверяет timestamps, source availability и forbidden features.

### Imbalance, calibration, error analysis

- imbalance policy фиксирует class weights/resampling/threshold role;
- probability calibration проверяется через Brier/log loss и calibration bins;
- segment error analysis показывает where model fails, not just average score;
- model card содержит intended use, out-of-scope use, metrics, slices, limitations,
  threshold, calibration и retraining notes.

## Интеграционный мини-проект

`15/15` собирает поставку:

```text
ml-baseline-package/
├── problem/
│   ├── problem-spec.json
│   ├── decision-policy.json
│   └── target-definition.md
├── data/
│   ├── source-contract.json
│   ├── feature-contract.json
│   ├── split-manifest.csv
│   ├── leakage-audit.json
│   └── quality-gates.json
├── features/
│   ├── feature-table.csv
│   ├── preprocessing-spec.json
│   └── transformed-feature-schema.json
├── models/
│   ├── dummy-baseline.json
│   ├── linear-baseline.json
│   ├── tree-diagnostics.json
│   ├── ensemble-candidate.json
│   └── pipeline-spec.json
├── evaluation/
│   ├── metric-report.json
│   ├── threshold-report.json
│   ├── calibration-report.json
│   ├── segment-error-analysis.csv
│   └── cv-results.csv
├── figures/
│   ├── confusion-matrix.png
│   ├── precision-recall-curve.png
│   ├── calibration-curve.png
│   └── segment-error-panel.png
├── model-card.md
├── decision.json
└── manifest.json
```

Пакет обязан:

- фиксировать business decision, prediction unit, target horizon и prediction time;
- публиковать feature availability audit до split/modeling;
- отличать train, validation и test roles;
- включать dummy baseline и linear baseline;
- хранить preprocessing как часть model pipeline;
- сравнивать models на одинаковых rows, folds, metrics и thresholds;
- показывать confusion matrix, PR-oriented metrics, calibration и segment slices;
- блокировать test-driven model selection;
- блокировать feature leakage, full-sample preprocessing и post-outcome features;
- ограничивать decision statement одним из статусов:
  `ship_baseline_with_limits`, `needs_more_data`, `data_quality_blocked`,
  `leakage_blocked`, `model_unstable`, `inconclusive`;
- связывать каждый статус с problem id, split ids, metrics, threshold, slices и
  limitations;
- выпускать SHA-256 manifest всех переданных файлов и generation parameters.

## Проверяемость

- Tiny-profile содержит ручные expected values для problem readiness, split assignment,
  confusion matrix, precision/recall, weighted cost, dummy baseline, threshold selection,
  calibration bins и segment error rows.
- Problem-framing tests проверяют prediction unit, target timing, negative class,
  eligible population, feature availability и no-causal-claim wording.
- Split tests ловят random row split, user leakage, temporal leakage и validation/test
  role confusion.
- Metric tests проверяют confusion matrix, precision/recall/FPR/FNR, PR AUC role,
  threshold budget и business-cost policy.
- Preprocessing tests ловят fit before split, unknown category, missing-value semantics
  и feature matrix schema drift.
- Pipeline tests проверяют `fit`/`transform` order, single estimator object, reproducible
  predictions и no manual preprocessing outside pipeline.
- ColumnTransformer tests проверяют numeric/categorical/binary routing, dropped columns
  и transformed feature names.
- Linear tests проверяют dummy baseline comparison, coefficient signs, regularization
  spec и intercept handling.
- Tree tests проверяют overfit diagnostics, depth/min samples policy и rule export.
- Ensemble tests проверяют random seed, OOB/CV diagnostics, feature importance warnings
  и stability across seeds.
- CV tests проверяют folds, grouping/time constraints, scoring alignment and no test
  peeking.
- Imbalance tests проверяют class distribution, baseline accuracy trap, threshold
  selection and positive-class metrics.
- Calibration tests проверяют Brier/log loss, calibration bins, calibrated vs uncalibrated
  scores and threshold impact.
- Leakage tests проверяют forbidden columns, availability timestamps, feature selection
  placement and validation-score cherry-picking.
- Error-analysis tests проверяют segment slices, small-n warnings and hidden aggregate
  failures.
- Final package test проверяет structure, manifest, checksums, model-card-to-evidence
  links, no unsupported causal wording and consistency between problem spec, data audit,
  splits, pipeline, metrics, calibration, errors and limitations.
