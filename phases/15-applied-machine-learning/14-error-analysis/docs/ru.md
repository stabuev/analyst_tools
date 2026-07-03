# Анализ ошибок по сегментам

> Overall score показывает среднюю историю, а error analysis показывает, кому именно модель ошибается.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** 15-applied-machine-learning/13-leakage  
**Время:** ~75 минут  
**Результат:** вы публикуете segment error analysis по test split: confusion rows, slice metrics, small-n warnings и hidden aggregate failures.

## Цели обучения

- Построить row-level confusion ledger для выбранного calibrated decision rule.
- Посчитать slice metrics по `segment_id`, `platform`, `country`, business cohorts и score bands.
- Не скрывать small-n срезы, но запрещать сильные claims по ним.
- Найти hidden aggregate failures, где overall metric выглядит нормально, а срез явно хуже.
- Выпустить `segment-error-analyzer` как handoff в model card.

## Проблема

После leakage audit baseline можно честно оценивать на test. У calibrated top-k есть общий `precision = 0.5` и `recall = 1.0` на tiny test. Это выглядит приемлемо для smoke test: один churned user найден, false negatives нет.

Но model card не должен говорить только "precision 0.5". В поддержке важно понимать, где именно модель ошибается. Если false positive сидит в `android`, `organic` или `low score band`, aggregate score это прячет. Если в срезе одна строка, rate может быть 0 или 1 просто от малой выборки. Такой срез нельзя удалить, но и нельзя продавать как надежную статистику.

В этом уроке вы превращаете test predictions в таблицу ошибок и набор честных сегментных предупреждений.

## Концепция

Error analysis начинается с одной строки на prediction unit.

| Поле | Зачем нужно |
|---|---|
| `snapshot_id` | сохраняет связь с prediction unit |
| `actual_label` | фактический churn outcome |
| `selected_for_action` | выбран ли пользователь budget rule |
| `confusion_label` | `tp`, `fp`, `tn`, `fn` |
| `segment_id`, `platform`, `country` | predeclared segment dimensions |
| `business_cohort`, `score_band` | business и score-based diagnostics |

Дальше та же таблица группируется по срезам. Для каждого среза считаются `tp/fp/tn/fn`, precision, recall, FPR/FNR, error rate, selection rate и Brier score. Overall row остается reference, а не заменой сегментного анализа.

Два правила защищают интерпретацию:

- `small_n_warning`: срез остается в отчете, но получает diagnostic-only статус;
- `hidden_failure_candidate`: срез хуже overall по error rate или precision gap и должен быть явно назван.

## Соберите это

### Шаг 1. Confusion row

Для budget decision rule бинарный прогноз не обязательно равен `score >= 0.5`. В уроке прогноз для действия - это `selected_at_budget_calibrated`.

```python
actual = bool(row["actual_label"])
selected = bool(row["selected_at_budget_calibrated"])

if selected and actual:
    confusion_label = "tp"
elif selected and not actual:
    confusion_label = "fp"
elif not selected and actual:
    confusion_label = "fn"
else:
    confusion_label = "tn"
```

Так `S009` становится false positive: пользователь выбран для offer, но не churned. `S010` становится true positive.

### Шаг 2. Score band

Score band помогает увидеть ошибки внутри шкалы вероятностей:

```python
bands = [
    ("low", 0.0, 0.3),
    ("medium", 0.3, 0.5),
    ("high", 0.5, 1.0),
]
```

В tiny profile `S009` имеет calibrated score `0.222222`, но выбран budget rule из-за tie/order effect после калибровки. Поэтому `low` score band попадает в hidden failure table.

### Шаг 3. Slice metrics

Для каждого среза:

```python
precision = tp / (tp + fp) if tp + fp else None
recall = tp / (tp + fn) if tp + fn else None
error_rate = (fp + fn) / row_count
selection_rate = (tp + fp) / row_count
```

Если `row_count < min_rows_per_slice`, срез получает `small_n_warning = true`. Это не ошибка расчета. Это запрет на уверенный вывод.

### Шаг 4. Hidden aggregate failure

Срез становится hidden failure candidate, если он достаточно крупный для диагностики и:

- error rate выше overall на заданный порог;
- или precision ниже overall на заданный порог.

В уроке такими срезами становятся `platform=android`, `acquisition_channel=organic`, `business_cohort=trial_basic:RU` и `score_band=low`.

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/15-applied-machine-learning/14-error-analysis/code/main.py
```

Короткий итог:

```json
{
  "audit_valid": true,
  "error_analysis_policy_id": "trial-churn-error-analysis-policy-v0",
  "analysis_split": "test",
  "row_count": 5,
  "overall_precision": 0.5,
  "overall_recall": 1.0,
  "false_positive_count": 1,
  "false_negative_count": 0,
  "small_n_slice_count": 19,
  "hidden_failure_slice_count": 4,
  "readiness_status": "ready_for_model_card_lesson"
}
```

CLI можно запускать напрямую:

```bash
uv run --locked python phases/15-applied-machine-learning/14-error-analysis/outputs/segment_error_analyzer.py \
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
  --error-analysis-policy-spec phases/15-applied-machine-learning/data/tiny/error_analysis_policy_spec.json \
  --feature-source-inventory phases/15-applied-machine-learning/data/tiny/feature_source_inventory.csv \
  --feature-availability phases/15-applied-machine-learning/data/tiny/ml_feature_availability.csv \
  --feature-selection-log phases/15-applied-machine-learning/data/tiny/ml_feature_selection_log.csv \
  --model-selection-log phases/15-applied-machine-learning/data/tiny/ml_model_selection_log.csv \
  --features phases/15-applied-machine-learning/data/tiny/ml_raw_features.csv \
  --labels phases/15-applied-machine-learning/data/tiny/ml_labels.csv \
  --manifest phases/15-applied-machine-learning/data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest phases/15-applied-machine-learning/data/tiny/ml_cv_fold_manifest.csv \
  --snapshots phases/15-applied-machine-learning/data/tiny/ml_scoring_snapshots.csv
```

## Сломайте это

1. Удалите `country` из `required_dimensions` в `error_analysis_policy_spec.json`. Analyzer должен заблокировать contract.
2. Сделайте leakage audit невалидным, например пометьте `churned_14d` как delivery feature. Segment analysis должен остановиться до расчетов.
3. Удалите test snapshot metadata. CLI должен вернуть structured runtime error без traceback.
4. Запустите с `--fail-on-warning`. Отчет остается valid, но exit code становится non-zero из-за small-n и hidden-failure warnings.

## Проверьте это

```bash
uv run --locked python -m unittest discover -s phases/15-applied-machine-learning/14-error-analysis/tests
```

Тесты проверяют:

- row-level confusion labels для `S009` и `S010`;
- overall metrics и 23 slice metric rows;
- 19 small-n warnings без удаления срезов;
- 4 hidden failure candidates;
- upstream leakage handoff;
- CLI behavior для invalid spec, runtime failure и `--fail-on-warning`.

## Поставьте результат

Named artifact:

```text
phases/15-applied-machine-learning/14-error-analysis/outputs/segment_error_analyzer.py
```

При запуске `code/main.py` урок публикует:

- `error_analysis_report.json`;
- `confusion_rows.csv`;
- `slice_metrics.csv`;
- `small_n_warnings.csv`;
- `hidden_failure_slices.csv`;
- `error_examples.csv`;
- `error_analysis_policy_audit.csv`;
- `error_analysis_serialized_spec.json`.

Handoff следующему уроку: `readiness_status = ready_for_model_card_lesson`. Model card должен цитировать не только overall precision, но и small-n/hidden-failure warnings.

## Упражнения

1. Добавьте score band `very_high` и проверьте, что интервалы остаются непрерывными.
2. Добавьте новый business slice `plan_id:platform` и объясните, какие срезы стали small-n.
3. Измените budget rule так, чтобы появился false negative, и проверьте, как изменились recall/FNR.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Confusion row | Confusion matrix достаточно хранить агрегатом | Одна строка на prediction unit с `tp/fp/tn/fn` и бизнес-контекстом |
| Slice metric | Любой segment rate является надежным фактом | Срезовая метрика требует minimum n и контекст интерпретации |
| Small-n warning | Малые срезы надо удалить | Малые срезы показываются, но остаются diagnostic-only |
| Hidden aggregate failure | Overall score уже все сказал | Срез может быть хуже overall и менять readiness narrative |
| Score band | Это новый threshold selection | Это diagnostic grouping, а не повторный выбор threshold на test |

## Дополнительное чтение

- [scikit-learn: model evaluation metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) - раздел про связь scoring, decision making и classification metrics.
- [scikit-learn: confusion_matrix](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html) - API для агрегированной confusion matrix; в уроке мы расширяем ее row-level ledger.
- [scikit-learn: classification_report](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.classification_report.html) - полезно сравнить стандартный aggregate report с slice-aware отчетом.
- [scikit-learn: probability calibration](https://scikit-learn.org/stable/modules/calibration.html) - контекст, почему score bands должны опираться на калиброванные вероятности, а не только на raw scores.
