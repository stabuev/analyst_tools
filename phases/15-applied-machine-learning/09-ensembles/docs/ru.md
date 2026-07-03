# Ансамбли деревьев

> Ансамбль не отменяет baseline: он просто добавляет еще одного кандидата, которого нужно
> проверить тем же протоколом.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/08-trees`  
**Время:** ~75 минут  
**Результат:** вы сравниваете tree ensemble с baselines, фиксируя random seed, stability
across seeds, feature-importance warnings и slice metrics.

## Цели обучения

- Обучить `RandomForestClassifier` внутри того же `Pipeline(ColumnTransformer, estimator)`.
- Сравнить ensemble с dummy, logistic и diagnostic tree на validation, не используя test для
  выбора.
- Измерить stability across seeds по `precision_at_budget` и выбранным `snapshot_id`.
- Выпустить MDI и permutation importance как диагностику, а не causal explanation.
- Опубликовать validation slice metrics и small-n warnings.

## Проблема

После `15/08` дерево нашло простое правило, идеально описало train и провалилось на
validation. Следующий соблазн: "пусть random forest усреднит деревья, и проблема уйдет".

Иногда так и бывает. Но в рабочем ML-процессе это не обещание, а проверяемая гипотеза.
На текущем tiny-profile random forest действительно делает вероятности менее экстремальными:

```text
decision_tree validation log_loss = 24.029102
random_forest validation log_loss = 1.004659
```

Но business metric не улучшается:

```text
dummy_prior validation precision_at_budget = 0.5
random_forest validation precision_at_budget = 0.0
```

Значит ансамбль не становится победителем. Он становится еще одним кандидатом в
comparison table, с явными warnings про tiny sample, seed stability и feature importance.

## Концепция

Random forest обучает несколько деревьев на bootstrap-сэмплах train rows и на случайных
подмножествах features. Затем классификатор усредняет вероятности деревьев. Это снижает
variance одного дерева, но не гарантирует улучшение целевой бизнес-метрики.

В этом уроке contract задает модель явно:

```json
{
  "model_id": "random_forest_depth2",
  "params": {
    "n_estimators": 25,
    "max_depth": 2,
    "max_features": "sqrt",
    "bootstrap": true,
    "random_state": 0,
    "n_jobs": 1
  }
}
```

Главные инварианты:

```text
fit only on train
select only on validation
test is final once-only evaluation
compare to upstream dummy/logistic/tree baselines
report seed stability before trusting improvement
publish feature importances with warnings
publish slice metrics with small-n flags
```

## Соберите это

Сначала посчитайте validation selection вручную. Random forest с `random_state = 0` дает:

| snapshot_id | label | score | selected_at_budget |
|---|---:|---:|---:|
| `S005` | 0 | 0.62 | 1 |
| `S006` | 1 | 0.38 | 0 |
| `S007` | 0 | 0.66 | 1 |

Budget равен двум offer actions, поэтому выбраны `S007` и `S005`. Оба отрицательные:

```text
precision_at_budget = 0 / 2 = 0.0
recall_at_budget = 0 / 1 = 0.0
```

Теперь проверьте seed stability:

| seed | selected_ids | precision_at_budget |
|---:|---|---:|
| 0 | `S005,S007` | 0.0 |
| 7 | `S006,S007` | 0.5 |
| 13 | `S005,S007` | 0.0 |

Range по `precision_at_budget` равен `0.5`. Это не blocking error, но важный сигнал:
на маленькой validation один seed меняет бизнес-решение.

## Используйте это

Урок поставляет CLI `tree-ensemble-comparator`:

```bash
python outputs/tree_ensemble_comparator.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/ensemble_report.json \
  --comparison-output outputs/ensemble_comparison.csv \
  --stability-output outputs/ensemble_stability_report.csv \
  --feature-importance-output outputs/ensemble_feature_importance.csv \
  --slice-metrics-output outputs/ensemble_slice_metrics.csv \
  --predictions-output outputs/ensemble_predictions.csv \
  --serialized-spec-output outputs/ensemble_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый итог:

```json
{
  "audit_valid": true,
  "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
  "model_id": "random_forest_depth2",
  "n_estimators": 25,
  "selected_model_id": "dummy_prior",
  "selected_model_source": "15/07-linear-baseline",
  "ensemble_validation_precision_at_budget": 0.0,
  "tree_validation_precision_at_budget": 0.0,
  "stability_range": 0.5,
  "top_mdi_feature": "categorical__plan_id_trial_pro",
  "top_permutation_feature": "binary__had_support_ticket_14d",
  "small_n_slice_count": 5,
  "readiness_status": "ready_for_cross_validation_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `ensemble_report.json` | Полный audit report, summary, checks и warnings. |
| `ensemble_comparison.csv` | Dummy/logistic/tree/ensemble metrics по validation/test и train diagnostics. |
| `ensemble_stability_report.csv` | Метрики и selected ids для seeds `0`, `7`, `13`. |
| `ensemble_feature_importance.csv` | MDI и permutation importance по transformed feature names. |
| `ensemble_slice_metrics.csv` | Validation metrics по `platform` и `country` с small-n flags. |
| `ensemble_predictions.csv` | Probability scores для train/validation/test. |
| `ensemble_serialized_spec.json` | sklearn version, model params, fit trace, selection и stability policy. |

## Сломайте это

Поменяйте selection data:

```json
{
  "comparison": {
    "selection_data": "test"
  }
}
```

Аудитор должен заблокировать spec:

```text
tree_ensemble_spec_declares_reproducible_comparison
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| Нет `random_state` | Нельзя воспроизвести ensemble score и выбранных пользователей. |
| Только один seed в `stability_policy` | Stability нельзя оценить по одному запуску. |
| Только MDI без permutation | Feature importance остается train-impurity diagnostic без held-out contrast. |
| Upstream tree diagnostic invalid | Ансамбль нельзя обсуждать без предыдущего non-linear handoff. |
| Validation slices без small-n flags | Segment metrics выглядят надежнее, чем они есть. |
| `n_jobs = -1` в учебном tiny contract | Параллелизм усложняет воспроизводимый trace без пользы для урока. |

Для строгого режима:

```bash
python outputs/tree_ensemble_comparator.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

На tiny-profile команда вернет non-zero из-за warnings про feature importance, small-n и
unknown categories.

## Проверьте это

Тесты проверяют:

- ensemble spec требует `RandomForestClassifier`, `random_state`, несколько seeds и
  validation-only selection;
- upstream `tree-diagnostic-trainer` проходит как handoff gate;
- `Pipeline.fit` получает только train rows;
- comparison table выбирает `dummy_prior`, а не ensemble;
- stability report показывает разные selected ids across seeds;
- MDI и permutation importance выведены по transformed feature names;
- slice metrics публикуют small-n warnings;
- CLI может падать на warning в strict mode.

Запуск:

```bash
python -m unittest phases/15-applied-machine-learning/09-ensembles/tests/test_main.py
```

## Поставьте результат

`outputs/tree_ensemble_comparator.py` можно использовать как model comparison gate перед
cross-validation. Он отвечает не на вопрос "какая модель моднее", а на рабочие вопросы:

- обогнал ли ensemble выбранный baseline на validation;
- меняются ли бизнес-действия при другом seed;
- какие transformed features модель считает важными и почему этому нельзя слепо верить;
- есть ли segment-level failures, скрытые aggregate metric.

На текущем tiny-profile вывод простой: random forest сглаживает вероятности одного дерева,
но не улучшает `precision_at_budget`. Поэтому следующий урок должен перейти к
cross-validation и fold design, а не к ручному подбору seed.

## Упражнения

1. Увеличьте `n_estimators` до `100` и проверьте, изменилась ли `stability_range`.
2. Поставьте `max_features = 1.0` и сравните top MDI features с текущим `sqrt`.
3. Уменьшите `max_allowed_range` до `0.25` и убедитесь, что stability warning становится
   явным.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Random forest | "Дерево, но всегда лучше" | Ансамбль деревьев с bootstrap и random feature subsets, который снижает variance, но должен сравниваться по выбранной метрике. |
| Seed stability | "random_state нужен только для красоты" | Проверка, меняются ли метрики и выбранные объекты при других seed. |
| MDI importance | "Объективная важность признака" | Train impurity-based diagnostic, чувствительный к cardinality и структуре train data. |
| Permutation importance | "Истинная причинная важность" | Held-out perturbation diagnostic, зависящий от score, sample size и корреляций features. |
| Slice metric | "Подробная метрика по сегменту" | Локальная проверка качества, которую нужно публиковать вместе с row count и small-n warning. |

## Дополнительное чтение

- [RandomForestClassifier - scikit-learn API](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html) - параметры `n_estimators`, `max_depth`, `max_features`, `bootstrap`, `random_state`, `n_jobs`.
- [Ensembles user guide](https://scikit-learn.org/stable/modules/ensemble.html) - как random forests уменьшают variance, чем отличаются от boosting и почему важны параметры `n_estimators` и `max_features`.
- [Permutation feature importance](https://scikit-learn.org/stable/modules/permutation_importance.html) - когда считать importance на held-out validation и почему она зависит от scoring function.
- [Feature importances with a forest of trees](https://scikit-learn.org/stable/auto_examples/ensemble/plot_forest_importances.html) - пример сравнения impurity-based importance и permutation importance на деревьях.
