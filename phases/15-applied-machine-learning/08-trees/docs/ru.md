# Деревья решений

> Дерево полезно не потому, что оно красивое, а потому что его переобучение видно глазами.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/07-linear-models`  
**Время:** ~75 минут  
**Результат:** вы обучаете decision tree как диагностическую non-linear модель, контролируя
depth/min samples, train-validation gap и rule export.

## Цели обучения

- Обучить `DecisionTreeClassifier` внутри того же `Pipeline(ColumnTransformer, estimator)`.
- Заранее ограничить `max_depth`, `min_samples_leaf`, `random_state` и diagnostic role.
- Сравнить train и validation, не выбирая дерево по train score и не используя test.
- Экспортировать readable rules с transformed feature names.
- Понять, почему tree rules не являются causal explanation и могут быть pure memorization.

## Проблема

В `15/07` logistic baseline проиграл `dummy_prior` на validation. Следующий соблазн:
"линейная модель слабая, давайте дерево, оно поймает non-linear pattern".

Это может быть хорошей диагностикой, но плохим решением без guardrails. На tiny-profile
дерево сразу находит короткое правило:

```text
categorical__platform_android > 0.500 -> class 1
```

На train оно выглядит идеально:

```text
precision_at_budget = 1.0
accuracy_at_0_5 = 1.0
log_loss = 0.0
```

А на validation проваливается:

```text
precision_at_budget = 0.0
accuracy_at_0_5 = 0.333333
log_loss = 24.029102
```

Значит дерево не "улучшило baseline". Оно показало readable overfit pattern, который
нужно опубликовать как warning.

## Концепция

Decision tree строит последовательность binary splits. Каждый leaf хранит распределение
классов train rows, попавших в этот leaf; `predict_proba` возвращает долю классов внутри
leaf. Поэтому pure leaf с двумя положительными train examples дает probability `1.0`, а
pure leaf с двумя отрицательными - `0.0`.

В этом уроке дерево имеет явный contract:

```json
{
  "model_id": "decision_tree_depth2",
  "params": {
    "criterion": "gini",
    "max_depth": 2,
    "min_samples_split": 2,
    "min_samples_leaf": 1,
    "random_state": 0
  }
}
```

Даже при `max_depth=2` фактическая глубина получилась `1`: первый split уже идеально
разделил четыре train rows. Это не победа, а красный флажок для tiny sample.

Главные инварианты:

```text
fit only on train
use train predictions only for gap diagnostics
compare tree to selected baseline on validation
export rules with transformed feature names
do not promote tree when validation is worse than baseline
```

## Соберите это

Сначала проверьте один split вручную. В train rows:

| snapshot_id | platform | transformed feature | label |
|---|---|---:|---:|
| `S001` | android | 1 | 1 |
| `S002` | ios | 0 | 0 |
| `S003` | web | 0 | 0 |
| `S004` | android | 1 | 1 |

Правило:

```python
def tree_score(platform_android: int) -> float:
    if platform_android <= 0.5:
        return 0.0
    return 1.0
```

На train оно идеально, но validation показывает перенос:

| snapshot_id | label | score | ошибка |
|---|---:|---:|---|
| `S005` | 0 | 0.0 | нет |
| `S006` | 1 | 0.0 | false negative |
| `S007` | 0 | 1.0 | false positive |

Top-2 по score на validation выбирает `S007` и `S005`, то есть `precision_at_budget = 0.0`.
У выбранного в `15/07` `dummy_prior` было `0.5`. Поэтому дерево остается diagnostic,
а не promoted baseline.

## Используйте это

Урок поставляет CLI `tree-diagnostic-trainer`:

```bash
python outputs/tree_diagnostic_trainer.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/tree_report.json \
  --overfit-output outputs/tree_overfit_report.csv \
  --node-output outputs/tree_node_report.csv \
  --rules-output outputs/tree_rules.txt \
  --predictions-output outputs/tree_predictions.csv \
  --serialized-spec-output outputs/tree_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый итог:

```json
{
  "audit_valid": true,
  "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
  "model_id": "decision_tree_depth2",
  "max_depth_limit": 2,
  "actual_tree_depth": 1,
  "leaf_count": 2,
  "split_features": ["categorical__platform_android"],
  "selected_linear_baseline_id": "dummy_prior",
  "tree_validation_precision_at_budget": 0.0,
  "baseline_validation_precision_at_budget": 0.5,
  "train_validation_gaps": {
    "accuracy_at_0_5": 0.666667,
    "precision_at_budget": 1.0,
    "log_loss": 24.029102
  },
  "warnings": [
    "tree_unknown_categories_bucketed",
    "tiny_tree_training_sample_expected",
    "tree_train_validation_gap_exceeds_threshold",
    "tree_diagnostic_worse_than_selected_baseline_on_validation"
  ],
  "readiness_status": "ready_for_tree_ensemble_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `tree_report.json` | Полный diagnostic report и checks. |
| `tree_overfit_report.csv` | Train/validation/test metrics и train-validation gaps. |
| `tree_node_report.csv` | Node-level tree structure: split feature, threshold, leaf counts. |
| `tree_rules.txt` | Compact readable rules через `export_text`. |
| `tree_predictions.csv` | Probability scores для train/validation/test. |
| `tree_serialized_spec.json` | sklearn version, tree params, split features и fit trace. |

`tree_rules.txt`:

```text
|--- categorical__platform_android <= 0.500
|   |--- weights: [2.000, 0.000] class: 0
|--- categorical__platform_android >  0.500
|   |--- weights: [0.000, 2.000] class: 1
```

## Сломайте это

Уберите depth limit:

```json
{
  "candidate": {
    "params": {
      "max_depth": null
    }
  }
}
```

Аудитор должен заблокировать spec:

```text
tree_diagnostic_spec_declares_constrained_tree
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| `selection_data = "test"` | Test нельзя использовать для выбора дерева. |
| Нет `random_state` | Tree construction может стать невоспроизводимым. |
| Нет `rule_export.require_feature_names` | Правила становятся нечитаемыми после ColumnTransformer. |
| Upstream linear baseline invalid | Нельзя строить дерево без baseline handoff. |
| Train содержит один класс | Диагностический classifier не проверяет binary separation. |
| Большой train-validation gap скрыт | Overfit становится невидимым для следующего урока. |

Для строгого режима:

```bash
python outputs/tree_diagnostic_trainer.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

На tiny-profile команда вернет non-zero из-за overfit warning.

## Проверьте это

Тесты проверяют:

- tree spec требует depth/min leaf/random state/rule export;
- upstream `linear-baseline-trainer` проходит как handoff gate;
- дерево fit-ится только на train;
- predictions покрывают train/validation/test, но train используется только для gap;
- node report и rules используют transformed feature names;
- train-validation gap публикуется по accuracy, precision@budget и log loss;
- дерево хуже `dummy_prior` на validation и получает warning;
- CLI может падать на warning в strict mode.

Запуск:

```bash
python -m unittest phases/15-applied-machine-learning/08-trees/tests/test_main.py
```

## Поставьте результат

`outputs/tree_diagnostic_trainer.py` можно использовать как diagnostic gate перед
ансамблями. Он не заменяет baseline selection, а добавляет evidence:

- какое простое non-linear правило дерево нашло;
- насколько train score отличается от validation score;
- какие transformed features попали в split;
- можно ли вообще обсуждать tree/ensemble дальше без скрытого test peeking.

На текущем tiny-profile вывод простой: дерево читаемое, но переобученное; следующий урок
про ансамбли должен начинаться с этого warning, а не с обещания "деревья всегда лучше".

## Упражнения

1. Поставьте `min_samples_leaf = 2` и объясните, почему на этом tiny-profile дерево все
   равно остается overfit-prone diagnostic.
2. Добавьте второй tree candidate с `criterion = "entropy"` и сравните rules, не используя
   test для выбора.
3. Удалите `require_feature_names` из spec и проверьте, что CLI блокирует rule export.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Decision tree | "Интерпретируемая модель, значит надежная" | Набор split rules, который может очень быстро переобучиться. |
| Max depth | "Косметическое ограничение" | Pre-pruning control, ограничивающий сложность правил. |
| Leaf probability | "Калиброванная вероятность" | Доля train labels внутри leaf; на маленьком leaf легко становится 0 или 1. |
| Train-validation gap | "Просто разница метрик" | Сигнал, что rule хорошо описал train, но плохо переносится. |
| Rule export | "Объяснение причины" | Читаемый trace split-ов в transformed feature space, не causal claim. |

## Дополнительное чтение

- [DecisionTreeClassifier - scikit-learn API](https://scikit-learn.org/stable/modules/generated/sklearn.tree.DecisionTreeClassifier.html) - параметры `criterion`, `max_depth`, `min_samples_leaf`, `class_weight`, `random_state`.
- [Decision Trees user guide](https://scikit-learn.org/stable/modules/tree.html) - преимущества, ограничения, overfitting, `max_depth` и `min_samples_leaf` как практические controls.
- [export_text - scikit-learn API](https://scikit-learn.org/stable/modules/generated/sklearn.tree.export_text.html) - компактный текстовый экспорт правил без Graphviz.
- [Understanding the decision tree structure](https://scikit-learn.org/stable/auto_examples/tree/plot_unveil_tree_structure.html) - как читать `tree_`, node ids, thresholds, children и leaf values.
