# Линейные baseline

> Baseline нужен не для красоты: он должен иметь право победить более сложную модель.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/06-column-transformer`  
**Время:** ~75 минут  
**Результат:** вы строите dummy и logistic/linear baseline, сравниваете их на validation,
фиксируете regularization, intercept и границы интерпретации коэффициентов.

## Цели обучения

- Обучить `DummyClassifier` и `LogisticRegression` как полный sklearn `Pipeline`.
- Сравнить модели на validation по predeclared budget metric, не используя test для выбора.
- Зафиксировать regularization, intercept, fitted classes и feature count.
- Связать коэффициенты logistic baseline с `ColumnTransformer.get_feature_names_out()`.
- Описать, почему коэффициенты не являются causal explanation и не доказывают эффект offer.

## Проблема

После `15/06` у нас есть честный preprocessing handoff:

```text
raw features
  -> ColumnTransformer
  -> transformed feature matrix with 24 named features
```

Теперь хочется сказать: "обучим логистическую регрессию и это будет baseline". Но без
dummy comparison это опасная фраза. Модель может:

- переобучиться на четырех train rows;
- красиво смотреться по одной метрике, но проиграть featureless floor;
- иметь коэффициенты, которые нельзя связать с transformed feature names;
- выглядеть как объяснение причин оттока, хотя это только predictive score.

В этом уроке tiny-profile специально оставляет неудобный результат: regularized logistic
baseline проигрывает `dummy_prior` на validation по `precision_at_budget`. Это не баг, а
правильный сигнал baseline gate.

## Концепция

Baseline comparison разделяет три роли:

| Роль | Что делает | Где используется |
|---|---|---|
| `train` | fit preprocessing и estimator | `Pipeline.fit` |
| `validation` | выбор baseline и threshold/budget decisions | model selection |
| `test` | финальная одноразовая проверка | не участвует в выборе |

Dummy baseline игнорирует input features и предсказывает только по `y`, увиденному на
fit. В нашем train split две положительные и две отрицательные метки, поэтому
`dummy_prior` дает probability `0.5` для каждого validation/test snapshot.

Logistic baseline использует тот же `ColumnTransformer`, но estimator уже смотрит на 24
transformed features:

```text
Pipeline(
  preprocess = ColumnTransformer(...),
  estimator = LogisticRegression(solver="liblinear", C=1.0, l1_ratio=0.0)
)
```

`C=1.0` и `l1_ratio=0.0` фиксируют L2-regularized baseline. `C` - inverse regularization
strength: чем меньше `C`, тем сильнее shrinkage. Intercept тоже сохраняется, потому что
он часть decision function, а не декоративная константа.

## Соберите это

Сначала посчитайте budget comparison без sklearn. Пусть offer budget равен двум строкам:

```python
rows = [
    {"snapshot_id": "S005", "label": 0, "score": 0.50},
    {"snapshot_id": "S006", "label": 1, "score": 0.50},
    {"snapshot_id": "S007", "label": 0, "score": 0.50},
]
budget = 2
top = sorted(rows, key=lambda row: (-row["score"], row["snapshot_id"]))[:budget]
precision_at_budget = sum(row["label"] for row in top) / budget
```

Tie-breaker по `snapshot_id` делает dummy ranking воспроизводимым. Для validation:

```text
dummy_prior top-2: S005, S006 -> precision_at_budget = 0.5
logistic_l2 top-2: S007, S005 -> precision_at_budget = 0.0
```

После этого добавьте сравнение по secondary metrics:

| Метрика | Зачем |
|---|---|
| `precision_at_budget` | соответствует ограниченному offer budget |
| `recall_at_budget` | показывает, нашли ли churned users |
| `average_precision` | смотрит на ranking по всем thresholds |
| `log_loss` | штрафует плохие вероятности |
| `accuracy_at_0_5` | только diagnostic, не primary metric |

Главный инвариант:

```text
fit on train only
select on validation only
report test, but never use test to select the baseline
```

## Используйте это

Урок поставляет CLI `linear-baseline-trainer`:

```bash
python outputs/linear_baseline_trainer.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/baseline_report.json \
  --comparison-output outputs/baseline_comparison.csv \
  --coefficients-output outputs/coefficient_table.csv \
  --predictions-output outputs/baseline_predictions.csv \
  --serialized-spec-output outputs/linear_baseline_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый итог:

```json
{
  "audit_valid": true,
  "linear_baseline_id": "trial-churn-linear-baseline-v0",
  "fit_split": "train",
  "fit_row_count": 4,
  "selection_split": "validation",
  "selected_model_id": "dummy_prior",
  "candidate_model_ids": ["dummy_prior", "logistic_l2"],
  "selection_budget": 2,
  "transformed_feature_count": 24,
  "coefficient_row_count": 24,
  "prediction_row_count": 16,
  "validation_precision_at_budget": {
    "dummy_prior": 0.5,
    "logistic_l2": 0.0
  },
  "warnings": [
    "linear_baseline_unknown_categories_bucketed",
    "tiny_linear_baseline_training_sample_expected",
    "linear_baseline_does_not_beat_dummy_on_tiny_validation"
  ],
  "readiness_status": "ready_for_tree_diagnostics_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `baseline_report.json` | Полный audit report и summary. |
| `baseline_comparison.csv` | Dummy/logistic metrics по validation и test. |
| `coefficient_table.csv` | Logistic coefficients, joined to transformed feature schema. |
| `baseline_predictions.csv` | Probability scores и selected-at-budget flags. |
| `linear_baseline_serialized_spec.json` | sklearn version, model params, selection trace и fit trace. |

## Сломайте это

Поменяйте selection split:

```json
{
  "comparison": {
    "selection_data": "test"
  }
}
```

Аудитор должен заблокировать spec:

```text
linear_baseline_spec_declares_dummy_and_logistic
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| Удалили `dummy_classifier` | Сложная модель больше не сравнивается с featureless floor. |
| Не указан regularization contract | Logistic baseline невоспроизводим и плохо интерпретируем. |
| Test row отмечен как выбранный baseline | Это test peeking. |
| Coefficients не join-ятся к feature schema | Нельзя понять, что означает coefficient. |
| Train содержит один класс | LogisticRegression не может честно обучить binary estimator. |
| Unknown category создает новую колонку | Schema drift между train и validation/test. |

Для строгого режима:

```bash
python outputs/linear_baseline_trainer.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

На tiny-profile команда вернет non-zero, потому что warning-и не скрываются.

## Проверьте это

Тесты проверяют:

- dummy и logistic fit-ятся как полные sklearn `Pipeline`;
- comparison table содержит validation/test rows для обеих моделей;
- model selection использует только validation;
- prediction rows не включают train;
- coefficient table содержит 24 строки, по одной на transformed feature;
- intercept и regularization сохраняются в serialized spec;
- invalid spec, invalid manifest и invalid upstream ColumnTransformer блокируются;
- warning-и про unknown categories, tiny train и проигрыш dummy не превращаются в silent success.

Запуск:

```bash
python -m unittest phases/15-applied-machine-learning/07-linear-models/tests/test_main.py
```

## Поставьте результат

`outputs/linear_baseline_trainer.py` можно использовать как standalone audit gate перед
следующим моделированием. Он принимает problem/preprocessing/pipeline/ColumnTransformer
contracts, raw features, labels и split manifest, а на выходе дает:

- selected baseline по validation;
- comparison metrics для dummy и logistic;
- fitted logistic coefficients с transformed feature names;
- explicit warning, если logistic не лучше dummy на validation;
- trace, который показывает, что validation/test не fit-или estimator.

Baseline готов к следующему уроку не потому, что logistic победила, а потому что сравнение
честно зафиксировано и не прячет слабый результат.

## Упражнения

1. Добавьте третий logistic candidate с меньшим `C` и объясните, почему selection все еще
   должен идти только по validation.
2. Пересчитайте `precision_at_budget` вручную для test rows, но не используйте его для
   выбора модели.
3. Добавьте колонку в raw features без route в `ColumnTransformer` и проверьте, что
   baseline trainer блокируется через upstream audit.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Dummy baseline | "Бесполезная модель для галочки" | Featureless floor, с которым сложная модель обязана честно сравниваться. |
| Linear baseline | "Простая модель всегда лучше dummy" | Проверяемый первый estimator; он может проиграть. |
| Intercept | "Неважная константа" | Bias term decision function, который влияет на probability. |
| Regularization | "Настройка качества" | Ограничение коэффициентов, меняющее magnitude и иногда sign. |
| Coefficient | "Причинный эффект feature" | Вес transformed feature в fitted predictive model при данном preprocessing и regularization. |

## Дополнительное чтение

- [DummyClassifier - scikit-learn API](https://scikit-learn.org/stable/modules/generated/sklearn.dummy.DummyClassifier.html) - посмотрите стратегии `prior`, `most_frequent`, `stratified` и почему input features игнорируются.
- [LogisticRegression - scikit-learn API](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) - разберите `C`, `l1_ratio`, `solver`, `fit_intercept` и совместимость solver/penalty.
- [Metrics and scoring - classification metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) - свяжите `log_loss`, `average_precision_score`, precision/recall и probability outputs.
- [Linear Models - logistic regression](https://scikit-learn.org/stable/modules/linear_model.html#logistic-regression) - прочитайте conceptual section про regularized logistic regression и границы linear classifiers.
