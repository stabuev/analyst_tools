# Data leakage

> Честная ML-оценка начинается не с метрики, а с доказательства, что модель не видела будущего.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** 15-applied-machine-learning/12-calibration  
**Время:** ~90 минут  
**Результат:** вы собираете leakage audit, который блокирует forbidden features, full-sample preprocessing, feature selection outside CV и выбор модели по test.

## Цели обучения

- Разделить признаки на доступные к `prediction_time` и запрещенные post-outcome candidates.
- Проверить, что preprocessing fit происходит только на train и живет внутри Pipeline/ColumnTransformer.
- Отличить безопасный feature contract от label-aware selector, обученного на all rows или validation/test labels.
- Зафиксировать, что validation выбирает модель, а test остается final once-only evaluation.
- Выпустить named artifact `ml-leakage-auditor` с evidence tables и blocking checks.

## Проблема

Команда уже собрала churn baseline: есть problem spec, split manifest, preprocessing contract, Pipeline, ColumnTransformer, линейные и tree baselines, cross-validation, imbalance policy и probability calibration. На tiny test calibrated top-k выглядит лучше, чем uncalibrated baseline.

Но хороший score сам по себе ничего не доказывает. В ML легко получить красивую метрику, если в обучение попал признак `churned_14d`, если imputer/scaler увидел весь датасет до split, если `SelectKBest` обучили на labels всех строк или если модель выбрали по лучшему test score.

В этом уроке вы строите слой защиты перед error analysis: не еще одну метрику, а audit trail, который отвечает на вопрос: "могла ли эта модель знать то, чего в production на момент скоринга еще нет?"

## Концепция

Leakage - это не только target column в features. В прикладном ML встречаются четыре рабочих класса риска.

| Риск | Как выглядит | Почему портит оценку |
|---|---|---|
| Forbidden/post-outcome features | `churned_14d`, future cancellation, accepted retention offer | Модель получает future outcome или следы intervention после скоринга |
| Full-sample preprocessing | imputer, scaler, encoder, target encoding fit до split | Holdout distribution или labels влияют на train-time transformations |
| Feature selection outside CV | `SelectKBest` на всех rows, pruning по validation score до CV | Validation/test labels косвенно выбирают модельную форму |
| Test cherry-picking | test metric участвует в выборе model/threshold | Test перестает быть независимой финальной проверкой |

Хороший leakage audit хранит не только verdict, но и evidence:

1. feature availability report;
2. forbidden-source table;
3. preprocessing scope audit;
4. feature-selection scope audit;
5. model-selection registry;
6. serialized spec для передачи в следующий урок.

## Соберите это

### Шаг 1. Зафиксируйте момент доступности признака

Минимальный feature availability row должен отвечать на пять вопросов:

```python
row = {
    "feature_name": "cancelled_after_prediction",
    "source_id": "cancellation_events_after_prediction",
    "timing": "post_prediction_time",
    "risk_type": "future_behavior_leakage",
    "used_in_delivery_model": False,
}
```

Решение строится не по имени колонки, а по contract:

```python
allowed_timings = {
    "known_before_prediction_time",
    "lookback_before_prediction_time",
}
forbidden_timings = {
    "post_prediction_time",
    "intervention_after_prediction_time",
    "label_after_prediction_time",
    "full_sample_label_aggregation",
}

candidate_allowed = row["timing"] in allowed_timings
blocking_if_used = row["used_in_delivery_model"] and row["timing"] in forbidden_timings
```

В реальном проекте это нужно подтверждать lineage и схемами источников. В уроке это делает `ml_feature_availability.csv` и `feature_source_inventory.csv`.

### Шаг 2. Проверьте preprocessing scope

Leakage бывает без target column. Если `SimpleImputer`, scaler, encoder или target encoder fit до split, validation/test уже повлияли на модель.

Минимальный audit row:

```python
row = {
    "component_type": "pipeline_spec",
    "declared_fit_split": "train",
    "preprocessing_location": "inside_pipeline",
}

valid = (
    row["declared_fit_split"] == "train"
    and row["preprocessing_location"] == "inside_pipeline"
)
```

В этом уроке аудитор проверяет сразу четыре upstream specs: preprocessing contract, Pipeline, ColumnTransformer и calibration policy.

### Шаг 3. Отделите feature contract от feature selection

Предзаданный business feature contract безопасен, если он объявлен до обучения и не использует labels. Label-aware selector безопасен только тогда, когда он fit внутри CV/Pipeline.

```python
selector = {
    "selector_id": "select_k_best_all_rows",
    "scope": "all_rows_before_split",
    "uses_labels": True,
    "inside_cv": False,
    "selected_for_delivery": False,
}
```

Такой selector может быть в audit как bad example, но не может быть выбран для delivery baseline.

### Шаг 4. Защитите test от выбора модели

Validation выбирает model/threshold. Test отвечает только на вопрос: "что получилось после зафиксированного выбора?"

```python
candidate = {
    "candidate_id": "leaky_test_best_threshold_0_5",
    "selection_split": "test",
    "test_metric_visible_to_selector": True,
    "selected_for_delivery": False,
}
```

Если такой candidate становится selected, audit должен вернуть blocking error.

## Используйте это

Запустите готовый пример из корня репозитория:

```bash
uv run --locked python phases/15-applied-machine-learning/13-leakage/code/main.py
```

Ожидаемый короткий итог:

```json
{
  "audit_valid": true,
  "leakage_policy_id": "trial-churn-leakage-policy-v0",
  "delivery_feature_count": 10,
  "forbidden_candidate_count": 5,
  "blocked_delivery_feature_count": 0,
  "test_used_for_model_selection": false,
  "readiness_status": "ready_for_error_analysis_lesson"
}
```

Артефакт можно запускать напрямую:

```bash
uv run --locked python phases/15-applied-machine-learning/13-leakage/outputs/ml_leakage_auditor.py \
  --spec phases/15-applied-machine-learning/data/tiny/problem_spec.json \
  --preprocessing-contract phases/15-applied-machine-learning/data/tiny/preprocessing_contract.json \
  --pipeline-spec phases/15-applied-machine-learning/data/tiny/pipeline_spec.json \
  --column-transformer-spec phases/15-applied-machine-learning/data/tiny/column_transformer_spec.json \
  --linear-baseline-spec phases/15-applied-machine-learning/data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec phases/15-applied-machine-learning/data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec phases/15-applied-machine-learning/data/tiny/tree_ensemble_spec.json \
  --cv-plan-spec phases/15-applied-machine-learning/data/tiny/cv_plan_spec.json \
  --imbalance-policy-spec phases/15-applied-machine-learning/data/tiny/imbalance_policy_spec.json \
  --calibration-policy-spec phases/15-applied-machine-learning/data/tiny/calibration_policy_spec.json \
  --leakage-policy-spec phases/15-applied-machine-learning/data/tiny/leakage_policy_spec.json \
  --feature-source-inventory phases/15-applied-machine-learning/data/tiny/feature_source_inventory.csv \
  --feature-availability phases/15-applied-machine-learning/data/tiny/ml_feature_availability.csv \
  --feature-selection-log phases/15-applied-machine-learning/data/tiny/ml_feature_selection_log.csv \
  --model-selection-log phases/15-applied-machine-learning/data/tiny/ml_model_selection_log.csv \
  --features phases/15-applied-machine-learning/data/tiny/ml_raw_features.csv \
  --labels phases/15-applied-machine-learning/data/tiny/ml_labels.csv \
  --manifest phases/15-applied-machine-learning/data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest phases/15-applied-machine-learning/data/tiny/ml_cv_fold_manifest.csv
```

Для CI можно добавить `--fail-on-warning`: тогда audit падает даже на видимых rejected candidates. Это полезно, если команда хочет запрещать хранение известных bad patterns рядом с delivery baseline.

## Сломайте это

Проверьте четыре failure mode.

1. Поставьте `used_in_delivery_model=true` для `churned_14d` в `ml_feature_availability.csv`. Audit должен заблокировать `leakage_no_forbidden_features_in_delivery_model`.
2. Измените `fit_split` в `preprocessing_contract.json` на `all_data`. Audit должен заблокировать preprocessing scope.
3. Сделайте `select_k_best_all_rows` выбранным selector. Audit должен заблокировать `leakage_feature_selection_not_outside_cv`.
4. Сделайте `leaky_test_best_threshold_0_5` selected candidate. Audit должен заблокировать `leakage_model_selection_uses_validation_not_test`.

В каждом случае правильное поведение - не "починить метрику", а остановить readiness.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/15-applied-machine-learning/13-leakage/tests
```

Тесты проверяют:

- happy path и `ready_for_error_analysis_lesson`;
- пять forbidden candidates: target leakage, label availability, future behavior, post-intervention outcome, full-sample target encoding;
- train-only preprocessing across upstream specs;
- rejected feature-selection patterns;
- rejected test cherry-pick candidate;
- CLI exit code для invalid spec и `--fail-on-warning`.

## Поставьте результат

Named artifact:

```text
phases/15-applied-machine-learning/13-leakage/outputs/ml_leakage_auditor.py
```

При запуске `code/main.py` урок публикует:

- `leakage_report.json`;
- `feature_availability_report.csv`;
- `forbidden_feature_report.csv`;
- `preprocessing_scope_audit.csv`;
- `feature_selection_audit.csv`;
- `model_selection_audit.csv`;
- `leakage_policy_audit.csv`;
- `leakage_serialized_spec.json`.

Главный handoff следующему уроку - `readiness_status = ready_for_error_analysis_lesson`. Если audit невалиден, error analysis нельзя интерпретировать как честный анализ ошибок модели.

## Упражнения

1. Добавьте новый forbidden candidate `payment_refunded_after_prediction` и опишите его source/timing/risk.
2. Смоделируйте safe label-aware selector, который работает внутри CV, и добавьте его в `ml_feature_selection_log.csv`.
3. Расширьте model-selection audit проверкой threshold selection: threshold может быть выбран на validation, но не на test.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Data leakage | Это только target column в features | Любой канал, через который train/selection получает информацию, недоступную при реальном prediction time |
| Prediction time | Дата выгрузки датасета | Момент, в который production-модель должна принять решение |
| Full-sample preprocessing | Безопасно, если не используются labels | Может подсмотреть validation/test distribution; fit должен быть train-only |
| Feature selection outside CV | Просто ускоряет обучение | Если selector label-aware и fit до split/CV, он переносит информацию holdout в модель |
| Test cherry-picking | Нормальный перебор вариантов | Test перестает быть независимым holdout, если участвует в выборе |

## Дополнительное чтение

- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) - прочитайте разделы про inconsistent preprocessing и data leakage: это базовая формулировка "split before preprocessing".
- [scikit-learn: Pipelines and composite estimators](https://scikit-learn.org/stable/modules/compose.html) - посмотрите, как Pipeline связывает preprocessing и estimator в один fit/predict contract.
- [scikit-learn: Feature selection](https://scikit-learn.org/stable/modules/feature_selection.html) - полезно для понимания, какие selectors label-aware и почему их нужно помещать внутрь CV.
- [scikit-learn: Permutation feature importance](https://scikit-learn.org/stable/modules/permutation_importance.html) - используйте после честной holdout-оценки как inspection tool, а не как способ выбрать признаки по test.
