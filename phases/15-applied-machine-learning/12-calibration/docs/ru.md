# Калибровка вероятностей

> Score может хорошо ранжировать пользователей и при этом быть плохой вероятностью.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/11-imbalanced-data`  
**Время:** ~75 минут  
**Результат:** вы проверяете probability calibration через bins, Brier/log loss и
сравниваете calibrated vs uncalibrated threshold decisions.

## Цели обучения

- Отличить ranking quality от calibrated probability.
- Построить calibration bins на independent calibration split.
- Посчитать Brier score, log loss и expected calibration error для raw и calibrated scores.
- Показать, как калибровка меняет fixed threshold decisions.
- Зафиксировать запрет на calibration fit и threshold selection по test.

## Проблема

После урока про imbalance selected model стала
`random_forest_depth2_class_weight_balanced`. Она выбрана по validation
`precision_at_budget`, но на test top-k промахивается:

```text
uncalibrated top-k test selected ids = S009,S012
precision_at_budget = 0.0
```

Это еще не вся проблема. Даже если top-k используется как primary decision rule, бизнес
часто задает вопросы в вероятностной шкале:

- "Если score 0.7, это правда примерно 70% churn risk?"
- "Можно ли ставить фиксированный threshold `0.5`?"
- "Какой expected error cost у calibrated threshold?"

Для таких вопросов мало знать порядок строк. Нужно проверить, похожи ли scores на
вероятности.

## Концепция

Калиброванная вероятность означает: среди объектов, которым модель дала примерно `0.6`,
событие должно происходить примерно в 60% случаев. На практике это проверяют через bins:

| Шаг | Что делаем |
|---|---|
| 1 | Берем score модели, обученной только на train. |
| 2 | На independent calibration split группируем scores в bins. |
| 3 | В каждом bin считаем `fraction_positive`. |
| 4 | Строим mapping `raw_score_bin -> calibrated_probability`. |
| 5 | На test только применяем mapping и считаем метрики. |

В большом production-профиле можно использовать `CalibratedClassifierCV` с sigmoid или
isotonic calibration. В tiny-профиле урока это было бы методологически сомнительно:
validation содержит всего 3 строки, а фолды не дадут надежного class coverage. Поэтому
урок строит прозрачный bin-map calibrator со сглаживанием и явно возвращает warnings.

Policy этого урока:

```json
{
  "calibration_method": {
    "kind": "validation_bin_map_with_laplace_smoothing",
    "bin_edges": [0.0, 0.5, 0.6, 1.0],
    "smoothing_alpha": 2.0,
    "prior_source": "calibration_split_positive_rate"
  },
  "metrics": {
    "proper_scoring_rules": ["brier_score", "log_loss"],
    "diagnostics": ["expected_calibration_error", "calibration_bins"]
  }
}
```

Сглаживание нужно, чтобы bin с одной строкой не превращал вероятность в жесткие `0` или
`1`. Формула для bin:

```text
calibrated_probability =
  (positive_count + alpha * validation_positive_rate) / (row_count + alpha)
```

## Соберите это

В validation split после 15/11 у selected model такие scores:

| snapshot_id | label | raw score | bin |
|---|---:|---:|---|
| `S005` | 0 | 0.46 | `[0.0, 0.5)` |
| `S006` | 1 | 0.50 | `[0.5, 0.6)` |
| `S007` | 0 | 0.64 | `[0.6, 1.0]` |

Validation positive rate:

```text
1 / 3 = 0.333333
```

Для первого bin:

```text
positive_count = 0
row_count = 1
alpha = 2

calibrated_probability =
  (0 + 2 * 0.333333) / (1 + 2)
  = 0.222222
```

Для второго bin:

```text
calibrated_probability =
  (1 + 2 * 0.333333) / (1 + 2)
  = 0.555556
```

Для третьего bin снова `0.222222`.

Теперь примените mapping к test:

| snapshot_id | label | raw score | calibrated score |
|---|---:|---:|---:|
| `S009` | 0 | 0.70 | 0.222222 |
| `S010` | 1 | 0.58 | 0.555556 |
| `S011` | 0 | 0.32 | 0.222222 |
| `S012` | 0 | 0.60 | 0.222222 |
| `S013` | 0 | 0.38 | 0.222222 |

На этом tiny test Brier score меняется так:

```text
uncalibrated_test_brier = 0.25464
calibrated_test_brier   = 0.079012
```

Но это не production claim: validation слишком маленький, bins содержат по одной строке,
поэтому auditor возвращает warnings.

## Используйте это

Запустите готовый пример:

```bash
python phases/15-applied-machine-learning/12-calibration/code/main.py
```

Он запишет:

```text
outputs/calibration_report.json
outputs/calibration_bins.csv
outputs/calibration_metrics.csv
outputs/calibrated_predictions.csv
outputs/calibration_threshold_impact.csv
outputs/calibration_policy_audit.csv
outputs/calibration_serialized_spec.json
```

Короткий stdout:

```json
{
  "audit_valid": true,
  "calibration_policy_id": "trial-churn-calibration-policy-v0",
  "source_model_id": "random_forest_depth2_class_weight_balanced",
  "uncalibrated_test_brier": 0.25464,
  "calibrated_test_brier": 0.079012,
  "test_fixed_threshold_0_5_action_count_uncalibrated": 3,
  "test_fixed_threshold_0_5_action_count_calibrated": 1,
  "readiness_status": "ready_for_leakage_lesson"
}
```

CLI можно запускать напрямую:

```bash
python phases/15-applied-machine-learning/12-calibration/outputs/probability_calibration_auditor.py \
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
  --features phases/15-applied-machine-learning/data/tiny/ml_raw_features.csv \
  --labels phases/15-applied-machine-learning/data/tiny/ml_labels.csv \
  --manifest phases/15-applied-machine-learning/data/tiny/ml_split_manifest.csv \
  --cv-fold-manifest phases/15-applied-machine-learning/data/tiny/ml_cv_fold_manifest.csv
```

## Сломайте это

Попробуйте три намеренные поломки.

1. Поставьте `"calibration_split": "test"` в `calibration_policy_spec.json`.
   Auditor должен заблокировать отчет через
   `calibration_policy_spec_declares_probability_contract`.

2. Замените `source_model_id` на `random_forest_depth2_unweighted`.
   Калибратор должен работать с моделью, выбранной imbalance policy, иначе handoff
   становится несогласованным.

3. Удалите `log_loss` из `metrics.proper_scoring_rules`.
   Один Brier score полезен, но policy требует оба proper scoring rules.

Для строгого CI можно включить warning gate:

```bash
python phases/15-applied-machine-learning/12-calibration/outputs/probability_calibration_auditor.py \
  ... \
  --fail-on-warning
```

На tiny profile команда должна завершиться ненулевым кодом, потому что warnings
ожидаемы и важны.

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest discover -s phases/15-applied-machine-learning/12-calibration/tests
```

Ключевые инварианты:

- `test_used_for_calibration == false`;
- `calibrated_on_split == "validation"` для всех predictions;
- `calibration_bins.csv` содержит validation и test rows, но bin probabilities learned on validation;
- `calibration_metrics.csv` содержит Brier score и log loss для `uncalibrated` и `calibrated`;
- fixed threshold impact считается отдельно от top-k budget rule.

## Поставьте результат

Именованный артефакт урока:

```text
outputs/probability_calibration_auditor.py
```

Он принимает problem/pipeline/imbalance/calibration specs, upstream data files и возвращает
`calibration_report.json`. В handoff следующего урока передавайте:

- `calibration_report.json` как summary вероятностной шкалы;
- `calibrated_predictions.csv` как score handoff;
- `calibration_policy_audit.csv` как evidence, что test не использовался для calibration fit;
- warnings как ограничения, которые нельзя скрывать в model card.

Урок считается завершенным, если:

```text
readiness_status = ready_for_leakage_lesson
blocking_errors = []
```

Warnings на tiny profile остаются: они не ломают урок, но запрещают переинтерпретировать
результат как production launch decision.

## Упражнения

1. Добавьте новый bin edge `0.7` и объясните, почему на tiny validation это ухудшает
   надежность оценки.
2. Замените fixed threshold `0.5` на `0.3` и сравните action count до и после calibration.
3. Добавьте в отчет колонку `calibration_gap_direction`: `overconfident`,
   `underconfident` или `aligned`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Calibration | Если модель лучше ранжирует, она автоматически calibrated. | Проверка соответствия predicted probability фактической частоте события. |
| Brier score | Это просто accuracy для вероятностей. | Средняя квадратичная ошибка probability prediction. |
| Log loss | Дублирует Brier score. | Proper scoring rule, который особенно сильно штрафует уверенные неверные вероятности. |
| Calibration split | Его можно заменить test split ради большей честности. | Отдельный split для fit калибратора; test остается только для final evaluation. |
| Fixed threshold | После calibration старый threshold можно переносить без проверки. | Threshold impact нужно пересчитать, потому что шкала probability изменилась. |

## Дополнительное чтение

- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) — прочитайте разделы про calibration curves, proper scoring rules и риск overfit у isotonic calibration.
- [scikit-learn: CalibratedClassifierCV](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.CalibratedClassifierCV.html) — посмотрите, как sklearn отделяет estimator fit от calibration fit через CV.
- [scikit-learn: brier_score_loss](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html) — проверьте API и интерпретацию Brier score для binary probabilities.
- [scikit-learn: calibration_curve](https://scikit-learn.org/stable/modules/generated/sklearn.calibration.calibration_curve.html) — сопоставьте ручные bins из урока с библиотечной функцией для reliability diagram.
