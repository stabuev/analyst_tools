# Несбалансированные классы

> При imbalance высокая accuracy может означать только то, что модель научилась игнорировать
> редкий, но бизнес-важный positive class.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/10-cross-validation`  
**Время:** ~75 минут  
**Результат:** вы диагностируете imbalance, ловушку accuracy, роль class weights/resampling
и threshold selection для ограниченного offer budget.

## Цели обучения

- Посчитать class distribution по train/validation/test и CV roles.
- Показать majority-class accuracy trap через always-negative baseline.
- Сравнить unweighted model и `class_weight="balanced"` без использования test для выбора.
- Отделить top-k budget rule от fixed threshold.
- Зафиксировать, что resampling допустим только на train/CV train, а не на validation/test.

## Проблема

В churn-задаче positive class - пользователь ушел в течение 14 дней. Таких пользователей
меньше, чем negative class. На final holdout в tiny-profile:

```text
positive_count = 1
negative_count = 4
positive_rate = 0.2
```

Модель, которая всегда говорит "не уйдет", получает:

```text
accuracy = 4 / 5 = 0.8
positive_recall = 0 / 1 = 0.0
balanced_accuracy = 0.5
```

Если смотреть только на accuracy, такая модель выглядит неплохо. Для бизнеса она бесполезна:
она не находит ни одного пользователя, которому нужно удерживающее предложение.

## Концепция

При class imbalance нельзя менять один слой и надеяться, что все стало честно. Нужны четыре
раздельных решения:

| Слой | Что фиксируем |
|---|---|
| Distribution | Сколько positive/negative в каждом split и CV role. |
| Metric policy | Accuracy только diagnostic, primary metric остается `precision_at_budget`. |
| Fit policy | `class_weight` или resampling считаются только на train/CV train. |
| Decision policy | При жестком offer budget используем top-k внутри scoring batch, а fixed threshold проверяем отдельно. |

В этом уроке policy говорит:

```json
{
  "comparison": {
    "primary_metric": "precision_at_budget",
    "forbidden_primary_metrics": ["accuracy", "accuracy_at_0_5"]
  },
  "class_weight_policy": {
    "class_weight": "balanced",
    "compute_on": "fit_split_only"
  },
  "threshold_policy": {
    "selection_data": "validation",
    "primary_decision_rule": "rank_top_k_within_scoring_batch"
  }
}
```

## Соберите это

Сначала посчитайте majority-class baseline вручную на test:

| snapshot_id | label | always_negative |
|---|---:|---:|
| `S009` | 0 | 0 |
| `S010` | 1 | 0 |
| `S011` | 0 | 0 |
| `S012` | 0 | 0 |
| `S013` | 0 | 0 |

Confusion matrix:

```text
TP = 0
FP = 0
FN = 1
TN = 4
```

Отсюда:

```text
accuracy = (TP + TN) / 5 = 0.8
positive_recall = TP / (TP + FN) = 0.0
balanced_accuracy = 0.5 * (positive_recall + negative_recall) = 0.5
```

Теперь сравните две версии random forest:

| model | validation precision@budget | validation selected ids | test precision@budget |
|---|---:|---|---:|
| `random_forest_depth2_unweighted` | 0.0 | `S005,S007` | 0.0 |
| `random_forest_depth2_class_weight_balanced` | 0.5 | `S006,S007` | 0.0 |

`class_weight="balanced"` помогает на validation: positive `S006` попадает в top-k. Но на
test top-k снова выбирает `S009,S012`, оба negative. Значит это не production promotion,
а сигнал для следующего слоя проверки: calibration, threshold policy и segment error
analysis.

## Используйте это

Урок поставляет CLI `imbalance-policy-evaluator`:

```bash
python outputs/imbalance_policy_evaluator.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --cv-plan-spec ../data/tiny/cv_plan_spec.json \
  --imbalance-policy-spec ../data/tiny/imbalance_policy_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest ../data/tiny/ml_cv_fold_manifest.csv \
  --output outputs/imbalance_report.json \
  --distribution-output outputs/class_distribution.csv \
  --baseline-trap-output outputs/baseline_trap_report.csv \
  --threshold-output outputs/imbalance_threshold_report.csv \
  --predictions-output outputs/imbalance_predictions.csv \
  --audit-output outputs/imbalance_policy_audit.csv \
  --serialized-spec-output outputs/imbalance_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый summary:

```json
{
  "audit_valid": true,
  "imbalance_policy_id": "trial-churn-imbalance-policy-v0",
  "selected_model_id": "random_forest_depth2_class_weight_balanced",
  "test_positive_rate": 0.2,
  "always_negative_test_accuracy": 0.8,
  "always_negative_test_positive_recall": 0.0,
  "validation_precision_at_budget": 0.5,
  "test_precision_at_budget": 0.0,
  "test_fixed_threshold_0_5_action_count": 3,
  "readiness_status": "ready_for_calibration_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `imbalance_report.json` | Полный report: summary, distribution, trap, comparison, thresholds, predictions, audit. |
| `class_distribution.csv` | Positive/negative counts и rates по split и CV roles. |
| `baseline_trap_report.csv` | Always-negative baseline с accuracy, balanced accuracy и recalls. |
| `imbalance_threshold_report.csv` | Top-k rule и fixed-threshold diagnostics по validation/test. |
| `imbalance_predictions.csv` | Scores unweighted и class-weighted candidates. |
| `imbalance_policy_audit.csv` | Checks и warnings по policy. |
| `imbalance_serialized_spec.json` | Class-weight policy, resampling policy, threshold policy и fit trace. |

## Сломайте это

Сделайте accuracy primary metric:

```json
{
  "comparison": {
    "primary_metric": "accuracy"
  }
}
```

Аудитор должен заблокировать spec:

```text
imbalance_policy_spec_declares_accuracy_weight_threshold_contract
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| `class_weight_policy.compute_on = "train_validation_pool"` | Class weights начинают видеть validation labels. |
| `threshold_policy.selection_data = "test"` | Test превращается в model-selection data. |
| `resampling_policy.forbid_resampling_validation_or_test = false` | Evaluation distribution перестает быть реальным scoring batch. |
| Upstream CV invalid | Imbalance policy нельзя строить поверх сломанного split/CV contract. |
| Fixed threshold выбран как production rule без budget check | На новом batch число действий может превысить offer budget. |

Строгий режим:

```bash
python outputs/imbalance_policy_evaluator.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --linear-baseline-spec ../data/tiny/linear_baseline_spec.json \
  --tree-diagnostic-spec ../data/tiny/tree_diagnostic_spec.json \
  --tree-ensemble-spec ../data/tiny/tree_ensemble_spec.json \
  --cv-plan-spec ../data/tiny/cv_plan_spec.json \
  --imbalance-policy-spec ../data/tiny/imbalance_policy_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest ../data/tiny/ml_cv_fold_manifest.csv \
  --fail-on-warning
```

На tiny-profile он вернет non-zero из-за expected warnings:

```text
imbalance_positive_rate_below_threshold
accuracy_trap_detected_on_test
class_weight_improves_validation_not_test_expected
fixed_threshold_can_exceed_offer_budget
```

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest phases/15-applied-machine-learning/11-imbalanced-data/tests/test_main.py
```

Проверки покрывают:

- class distribution по split/CV roles;
- always-negative accuracy trap на test;
- validation-only выбор class-weighted candidate;
- top-k budget rule против fixed thresholds;
- prediction trace без test selection;
- negative cases для accuracy primary, class-weight scope, resampling validation/test,
  threshold selection on test и invalid upstream CV.

Дополнительная проверка данных:

```bash
python phases/15-applied-machine-learning/data/generate_data.py \
  --check \
  --output phases/15-applied-machine-learning/data/tiny
```

## Поставьте результат

Именованный артефакт:

```text
outputs/imbalance_policy_evaluator.py
```

Он принимает upstream specs и shared tiny profile, затем выпускает imbalance package.
Для переноса на другой case сохраните тот же минимум:

```text
labels with positive/negative class
split manifest with train/validation/test roles
model scores or fit-able pipeline
business budget
metric policy where accuracy is diagnostic-only
```

Перед следующим уроком проверьте:

```text
summary.test_used_for_selection == false
summary.readiness_status == "ready_for_calibration_lesson"
```

## Упражнения

1. Измените threshold `0.6` и объясните, почему validation recall падает до `0.0`.
2. Добавьте строку в `class_distribution.csv` по `platform` и найдите самый рискованный slice.
3. Сделайте `resampling_policy.allowed = true`, но оставьте `if_enabled_fit_scope` только для train.
4. Добавьте candidate с `class_weight="balanced_subsample"` и сравните selected ids.
5. Сформулируйте, какую проверку должен добавить следующий урок calibration перед fixed threshold.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Class imbalance | Просто мало строк в датасете. | Positive и negative classes имеют разные доли, поэтому naive metrics могут вводить в заблуждение. |
| Accuracy trap | Accuracy всегда понятна бизнесу. | Высокая accuracy может скрывать нулевой recall по minority/positive class. |
| Balanced accuracy | Новая primary metric на все случаи. | Macro-average recall по классам, полезная диагностика imbalance, но не обязательно бизнес-метрика. |
| Class weight | Гарантированное исправление модели. | Вес ошибок классов внутри fit; не заменяет validation, calibration и threshold policy. |
| Resampling | Можно балансировать любой split. | Менять можно только training distribution, evaluation distribution должна оставаться честной. |
| Top-k budget rule | То же самое, что fixed threshold. | Top-k сохраняет жесткий budget внутри batch; fixed threshold может выбрать больше или меньше действий. |

## Дополнительное чтение

- [scikit-learn: `compute_class_weight`](https://scikit-learn.org/stable/modules/generated/sklearn.utils.class_weight.compute_class_weight.html) - формула `balanced` weights и границы применения class weights.
- [scikit-learn: `RandomForestClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html) - параметры `class_weight="balanced"` и `"balanced_subsample"` для деревьев.
- [scikit-learn: Metrics and scoring](https://scikit-learn.org/stable/modules/model_evaluation.html) - разделы про `balanced_accuracy`, precision/recall, average precision и threshold metrics.
- [scikit-learn: `DummyClassifier`](https://scikit-learn.org/stable/modules/generated/sklearn.dummy.DummyClassifier.html) - baseline strategies, которые помогают обнаружить majority-class trap.
