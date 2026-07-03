# Cross-validation

> Cross-validation полезна только тогда, когда folds повторяют реальный способ проверки:
> не смешивают пользователей, не тренируются на будущем и не трогают final holdout.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/09-ensembles`  
**Время:** ~75 минут  
**Результат:** вы проектируете cross-validation folds, которые уважают group/time
constraints, scoring policy и запрет test peeking.

## Цели обучения

- Отличить model-selection pool от final holdout test.
- Описать CV contract: fold id, role, group key, time key, scoring и output files.
- Проверить, что один `user_id` не попадает одновременно в train и validation внутри fold.
- Fit-ить `Pipeline(ColumnTransformer, estimator)` отдельно на `cv_train` каждого fold.
- Выпустить fold-level score report, validation predictions, serialized spec и no-peeking audit.

## Проблема

После `15/09` у нас есть несколько кандидатов: dummy baseline, logistic regression, одно
дерево и random forest. Один validation split слишком мал, чтобы делать уверенный вывод:

```text
random_forest validation precision_at_budget = 0.0
dummy_prior validation precision_at_budget = 0.5
```

Но просто написать `cv=5` тоже нельзя. В churn-задаче строки имеют пользователей и время.
Если один пользователь окажется в train и validation одного fold, validation станет слишком
оптимистичной. Если fold обучается на строках позже validation, появится temporal leakage.
Если CV затронет `test`, финальная проверка перестанет быть финальной.

Значит задача урока - не "включить cross-validation", а спроектировать проверяемый
cross-validation contract.

## Концепция

В этом курсе есть три уровня данных:

| Уровень | Роль |
|---|---|
| `train` | Fit preprocessing и estimator. |
| `validation` | Model selection, threshold/budget selection, diagnostics. |
| `test` | Final once-only evaluation после выбора модели и протокола. |

Cross-validation живет внутри model-selection pool. Для tiny-profile этот pool состоит из
`train` и `validation`, а `test` остается снаружи:

```json
{
  "model_selection_pool_splits": ["train", "validation"],
  "final_holdout_split": "test"
}
```

Fold manifest делает это явным:

```text
fold_id, snapshot_id, original_split, cv_role, group_key, prediction_time
cv_fold_1, S001, train, cv_train, U001, 2026-05-10
cv_fold_1, S002, train, cv_train, U002, 2026-05-10
cv_fold_1, S003, train, cv_validation, U003, 2026-05-10
cv_fold_1, S004, train, cv_validation, U004, 2026-05-10
cv_fold_2, S001, train, cv_train, U001, 2026-05-10
cv_fold_2, S002, train, cv_train, U002, 2026-05-10
cv_fold_2, S003, train, cv_train, U003, 2026-05-10
cv_fold_2, S004, train, cv_train, U004, 2026-05-10
cv_fold_2, S005, validation, cv_validation, U005, 2026-05-17
cv_fold_2, S006, validation, cv_validation, U006, 2026-05-17
cv_fold_2, S007, validation, cv_validation, U007, 2026-05-17
```

Инварианты:

```text
no original_split == test inside CV
no group_key overlap between cv_train and cv_validation within a fold
max(cv_train.prediction_time) <= min(cv_validation.prediction_time)
each fold role contains both classes
primary metric equals the model-selection metric from tree_ensemble_spec
Pipeline is fit only on cv_train for each fold
```

## Соберите это

Сначала проверьте fold manifest без sklearn. Для каждого fold соберите train/validation
groups:

```python
train_groups = {row["group_key"] for row in rows if row["cv_role"] == "cv_train"}
validation_groups = {row["group_key"] for row in rows if row["cv_role"] == "cv_validation"}
assert not (train_groups & validation_groups)
```

Затем проверьте время:

```python
max_train_time = max(row["prediction_time"] for row in rows if row["cv_role"] == "cv_train")
min_validation_time = min(
    row["prediction_time"] for row in rows if row["cv_role"] == "cv_validation"
)
assert max_train_time <= min_validation_time
```

И только после этого fit-ьте модель. Внутри каждого fold:

```python
pipeline = Pipeline(
    steps=[
        ("preprocess", column_transformer),
        ("model", random_forest),
    ]
)
pipeline.fit(X_train_fold, y_train_fold)
scores = pipeline.predict_proba(X_validation_fold)[:, 1]
```

Важно: `ColumnTransformer` тоже fit-ится внутри fold. Если fit-ить preprocessing на полном
датасете до CV, категории, медианы, scaling и другие параметры уже увидят validation/test.

На tiny-profile получаются такие fold scores:

| fold | train rows | validation rows | selected ids | precision@budget | log loss |
|---|---:|---:|---|---:|---:|
| `cv_fold_1` | 2 | 2 | `S003,S004` | 0.5 | 0.737454 |
| `cv_fold_2` | 4 | 3 | `S005,S007` | 0.0 | 1.004659 |

Средний результат:

```text
mean_precision_at_budget = 0.25
mean_log_loss = 0.871057
```

Это не делает random forest победителем. Это показывает, что результат нестабилен и перед
production-решением нужны следующие уроки: imbalance, probability calibration и leakage
audit.

## Используйте это

Урок поставляет CLI `cross-validation-planner`:

```bash
python outputs/cross_validation_planner.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --cv-plan-spec ../data/tiny/cv_plan_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest ../data/tiny/ml_cv_fold_manifest.csv \
  --output outputs/cv_report.json \
  --fold-manifest-output outputs/cv_fold_manifest.csv \
  --score-output outputs/cv_score_report.csv \
  --predictions-output outputs/cv_predictions.csv \
  --audit-output outputs/cv_no_peeking_audit.csv \
  --serialized-spec-output outputs/cv_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый summary:

```json
{
  "audit_valid": true,
  "cv_plan_id": "trial-churn-cv-plan-v0",
  "fold_count": 2,
  "model_id": "random_forest_depth2",
  "primary_metric": "precision_at_budget",
  "mean_precision_at_budget": 0.25,
  "mean_log_loss": 0.871057,
  "cv_validation_row_count": 5,
  "final_holdout_split": "test",
  "test_used_in_cv": false,
  "warnings": ["tiny_cv_fold_count_expected", "tiny_cv_validation_sample_expected"],
  "readiness_status": "ready_for_imbalance_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `cv_report.json` | Полный report: summary, fold manifest, scores, predictions, audit, serialized spec. |
| `cv_fold_manifest.csv` | Нормализованный fold manifest с числовым label. |
| `cv_score_report.csv` | Fold-level `precision_at_budget`, `recall_at_budget`, `log_loss`, selected ids. |
| `cv_predictions.csv` | Validation-only predictions каждого fold. |
| `cv_no_peeking_audit.csv` | Проверки no-test-peeking, group isolation, temporal order и scoring alignment. |
| `cv_serialized_spec.json` | sklearn version, model params, fold strategy, scoring и fit trace. |

## Сломайте это

Добавьте test row в fold manifest:

```csv
cv_fold_1,1,S009,U009,2026-05-24T09:00:00+03:00,test,cv_train,U009,false
```

Аудитор должен заблокировать отчет:

```text
cv_fold_manifest_excludes_final_test
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| Одинаковый `group_key` в `cv_train` и `cv_validation` | Validation видит того же пользователя, что и train. |
| `cv_train.prediction_time` позже `cv_validation.prediction_time` | Модель учится на будущем. |
| Fold role содержит только один класс | Метрики классификации становятся хрупкими или неинтерпретируемыми. |
| `scoring.primary_metric` отличается от ensemble comparison | CV уже не отвечает на тот же вопрос выбора модели. |
| `audit_policy.forbid_test_rows_in_cv = false` | Contract перестает защищать final holdout. |
| Upstream ensemble audit invalid | CV нельзя строить поверх неподтвержденного candidate handoff. |

Строгий режим может падать даже на warnings:

```bash
python outputs/cross_validation_planner.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --cv-plan-spec ../data/tiny/cv_plan_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest ../data/tiny/ml_cv_fold_manifest.csv \
  --fail-on-warning
```

На tiny-profile это вернет non-zero из-за малого числа folds и маленьких validation samples.
Для урока это warning, потому что no-peeking contract соблюден. Для production это сигнал
увеличить историю, число групп и размер holdout.

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest phases/15-applied-machine-learning/10-cross-validation/tests/test_main.py
```

Проверки покрывают:

- happy path с `mean_precision_at_budget = 0.25`;
- отсутствие `test` строк в CV outputs;
- group isolation и temporal order;
- validation-only predictions;
- serialized fit trace без test ids;
- negative cases для test peeking, group overlap, future train rows и scoring mismatch;
- CLI non-zero для invalid spec и `--fail-on-warning`.

Дополнительная проверка данных:

```bash
python phases/15-applied-machine-learning/data/generate_data.py \
  --check \
  --output phases/15-applied-machine-learning/data/tiny
```

## Поставьте результат

Именованный артефакт:

```text
outputs/cross_validation_planner.py
```

Он принимает problem/pipeline/model specs, `ml_split_manifest.csv` и
`ml_cv_fold_manifest.csv`, затем выпускает воспроизводимый CV package. Его можно
переиспользовать для другого small ML case, если сохранить тот же contract:

```text
snapshot_id
user_id
prediction_time
original_split
cv_role
group_key
label
```

Перед следующим уроком проверьте два поля:

```text
summary.test_used_in_cv == false
summary.readiness_status == "ready_for_imbalance_lesson"
```

## Упражнения

1. Добавьте третий fold, где validation содержит новые группы из более позднего времени.
2. Замените `primary_metric` на `average_precision` и посмотрите, какие checks блокируются.
3. Сделайте fold с одним положительным классом только в train и объясните, почему это опасно.
4. Добавьте в `cv_score_report.csv` `fold_positive_rate` и `validation_positive_rate`.
5. Спроектируйте production-вариант: сколько минимум групп и validation rows вы потребуете
   перед тем, как warning станет error?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cross-validation | Можно поставить `cv=5` в любой задаче. | Повторная проверка модели на нескольких folds, где split strategy должна соответствовать данным. |
| Fold manifest | Вспомогательная таблица без методологии. | Явный contract, какие строки входят в train/validation каждого fold и почему. |
| Group-aware CV | Просто stratification по классам. | Split, который не допускает пересечения групп между train и validation внутри fold. |
| Time-aware CV | Любой случайный split с датой в данных. | Проверка, где train не содержит строк позже validation. |
| Final holdout | Еще один fold для подбора модели. | Отложенный test, который используется один раз после выбора протокола. |
| Scoring policy | Набор удобных метрик после факта. | Предварительно объявленный критерий выбора и secondary diagnostics. |

## Дополнительное чтение

- [scikit-learn: Cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html) - прочитайте разделы про held-out test set, `cross_validate` и leakage через preprocessing.
- [scikit-learn: `cross_validate`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.cross_validate.html) - посмотрите API для нескольких metrics и возврата estimator/indices, когда нужен расширенный audit trail.
- [scikit-learn: `GroupKFold`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html) - сравните его с manifest-подходом урока: группы не пересекаются, но time order нужно контролировать отдельно.
- [scikit-learn: `StratifiedGroupKFold`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedGroupKFold.html) - разберите компромисс между class balance и group isolation, особенно на маленьких данных.
