# Сегментный анализ сильной модели

> Сильная модель полезна только там, где она улучшает решение, а не только выглядит сложнее.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** 16-tabular-ml/06-shap  
**Время:** ~75 минут  
**Результат:** вы сравниваете phase-15 baseline и early-stopped CatBoost на validation split по segment, score band и business cohort, сохраняя baseline deltas, small-n warnings и hidden-failure slices.

## Цели обучения

- Построить общий confusion ledger для baseline и CatBoost на одних и тех же validation rows.
- Посчитать slice metrics по `segment_id`, `platform`, `country`, business dimensions и score bands.
- Считать deltas `CatBoost - baseline`, а не смотреть на метрики моделей изолированно.
- Не скрывать small-n срезы, но запрещать сильные claims по ним.
- Найти slices, где strong model ухудшает action set: новые false positives, новые false negatives и смена score band.
- Выпустить `strong-model-segment-analyzer` как handoff в cost-sensitive decision lesson.

## Проблема

После `16/06` у нас есть объяснения CatBoost: Tree SHAP показывает, что модель реально использует `platform`. Это еще не значит, что модель полезнее baseline. В phase-15 baseline уже есть decision rule, risk register и model card. Чтобы заменить его strong model, надо ответить на другой вопрос:

```text
На тех же validation users и при том же action budget CatBoost улучшает решение или просто меняет, кому ошибаться?
```

В tiny fixture ответ неприятный, зато учебно честный. Baseline выбирает `S007` и `S006`: один false positive и один true positive. Early-stopped CatBoost выбирает `S007` и `S005`: два false positives, а единственный churned user `S006` становится false negative.

Средняя сводка уже плохая:

| Metric | Baseline | CatBoost | Delta |
|---|---:|---:|---:|
| Precision | 0.5 | 0.0 | -0.5 |
| Recall | 1.0 | 0.0 | -1.0 |
| Error rate | 0.333333 | 1.0 | +0.666667 |

Но lesson не о том, чтобы сказать "CatBoost плохой". Lesson о том, чтобы показать где именно он ломает решение и почему такой отчет должен идти перед threshold/cost discussion.

## Концепция

Сегментное сравнение strong model начинается не с importance, а с единого ledger:

| Поле | Зачем нужно |
|---|---|
| `model_role` | отделяет `baseline` от `catboost` |
| `snapshot_id` | гарантирует один и тот же prediction unit |
| `score` | score конкретной модели |
| `selected_for_action` | выбран ли user в top-k budget |
| `confusion_label` | `tp`, `fp`, `tn`, `fn` для action decision |
| `segment_id`, `platform`, `country` | predeclared product slices |
| `plan_id`, `acquisition_channel` | business slices |
| `business_cohort`, `score_band` | derived diagnostics |

Дальше каждая модель агрегируется одинаково. Для каждого slice считаются:

```text
precision = tp / (tp + fp)
recall = tp / (tp + fn)
error_rate = (fp + fn) / row_count
selection_rate = (tp + fp) / row_count
```

Ключевой объект урока - delta row:

```text
delta = metric_catboost - metric_baseline
```

Если `error_rate_delta > 0`, `precision_delta < 0` или `recall_delta < 0`, slice получает reason. Если появились новые `false_positive_ids` или `false_negative_ids`, они записываются явно. Так отчет говорит не "модель хуже вообще", а "CatBoost добавил FP `S005` и потерял TP `S006`".

Score band здесь model-specific. Baseline score `S006 = 0.5` попадает в `high`, а CatBoost score `S006 = 0.492308` попадает в `medium`. Это не ошибка: band считается по score каждой модели. Но это warning для интерпретации, потому что `score_band=high` у baseline и `score_band=high` у CatBoost уже не одна и та же подвыборка.

## Соберите это

### Шаг 1. Policy spec

Новый contract:

```text
phases/16-tabular-ml/data/tiny/strong_model_segment_policy_spec.json
```

Он фиксирует:

- `analysis_split=validation`;
- `final_holdout_split=test`, который нельзя использовать для segment analysis;
- baseline model `random_forest_depth2_class_weight_balanced`;
- candidate model `catboost_depth2_native_categories_es_logloss`;
- action budget `2`;
- required dimensions `segment_id`, `platform`, `country`;
- business dimensions `plan_id`, `acquisition_channel`;
- derived dimensions `business_cohort`, `score_band`;
- score band policy `low/medium/high`;
- small-n policy `warn_not_hide`;
- delta policy для worse-than-baseline slices;
- warning policy для small-n, hidden failures, band shifts и no-promotion.

### Шаг 2. Confusion rows

Для каждой модели строится одинаковая row-level таблица. Budget decision - это не `score >= 0.5`, а top-k selection:

```python
if selected and actual == 1:
    confusion_label = "tp"
elif selected and actual == 0:
    confusion_label = "fp"
elif not selected and actual == 1:
    confusion_label = "fn"
else:
    confusion_label = "tn"
```

Baseline берет готовый `selected_at_budget` из phase-15 imbalance output. CatBoost заново score'ится early-stopped model из `16/03`, сортируется по `score desc, split_order asc, snapshot_id asc` и выбирает top-2.

### Шаг 3. Slice metrics

Один и тот же ledger группируется по:

```text
overall
segment_id
platform
country
plan_id
acquisition_channel
business_cohort
score_band
```

Small slices не удаляются. В tiny validation почти каждый slice имеет `row_count < 3`, поэтому они diagnostic-only. Это не мешает увидеть новый FP/FN, но запрещает продавать срез как устойчивую статистику.

### Шаг 4. Baseline deltas

Для каждого `(dimension, slice_value)` analyzer строит строку:

```text
baseline_precision, candidate_precision, precision_delta
baseline_recall, candidate_recall, recall_delta
baseline_error_rate, candidate_error_rate, error_rate_delta
baseline_false_positive_ids, candidate_false_positive_ids
baseline_false_negative_ids, candidate_false_negative_ids
```

В `country=RU` baseline не ошибается, а CatBoost ошибается на обеих строках:

| Slice | Baseline error | CatBoost error | Reason |
|---|---:|---:|---|
| `country=RU` | 0.0 | 1.0 | new FP `S005`, new FN `S006` |

### Шаг 5. Warning ledger

Warnings не делают отчет invalid. Они делают interpretation честной:

- `strong_model_small_n_slices_visible`;
- `strong_model_hidden_failure_slices_visible`;
- `candidate_worse_than_baseline_on_validation`;
- `score_band_membership_differs_between_models`;
- `candidate_not_promoted_without_segment_gain`.

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/07-segment-analysis/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "segment_analysis_audit_id": "trial-churn-strong-model-segment-audit-v0",
  "baseline_model_id": "random_forest_depth2_class_weight_balanced",
  "early_stopping_model_id": "catboost_depth2_native_categories_es_logloss",
  "analysis_split": "validation",
  "baseline_precision": 0.5,
  "catboost_precision": 0.0,
  "precision_delta": -0.5,
  "baseline_recall": 1.0,
  "catboost_recall": 0.0,
  "error_rate_delta": 0.666667,
  "hidden_failure_slice_count": 13,
  "small_n_slice_count": 36,
  "score_band_shift_count": 1,
  "readiness_status": "ready_for_cost_sensitive_decision_lesson"
}
```

После запуска появляются файлы:

- `strong_model_segment_report.json` - полный report, summary, checks и warnings;
- `strong_model_confusion_rows.csv` - row-level comparison по двум моделям;
- `strong_model_slice_metrics.csv` - metrics по всем slices и обеим моделям;
- `strong_model_segment_deltas.csv` - baseline-to-CatBoost deltas;
- `strong_model_hidden_failure_slices.csv` - slices, где CatBoost хуже baseline;
- `strong_model_small_n_warnings.csv` - diagnostic-only small slices;
- `strong_model_score_band_shifts.csv` - rows, где score band сменился между моделями;
- `strong_model_segment_policy_audit.csv` - machine-readable checks;
- `strong_model_segment_serialized_spec.json` - handoff для `16/08`.

Ключевые строки:

| Snapshot | Baseline | CatBoost | Смысл |
|---|---|---|---|
| `S005` | `tn`, not selected | `fp`, selected | CatBoost добавил новый false positive |
| `S006` | `tp`, selected | `fn`, not selected | CatBoost потерял единственный positive user |
| `S007` | `fp`, selected | `fp`, selected | Ошибка осталась в обеих моделях |

Поэтому корректный вывод:

```text
Early-stopped CatBoost не продвигается вместо phase-15 baseline.
Он может идти в следующий cost-sensitive lesson только как candidate для анализа threshold/cost,
а не как улучшение, доказанное сегментами.
```

## Сломайте это

Поставьте в policy:

```json
"test_used_for_segment_analysis": true
```

Analyzer должен заблокировать отчет до расчетов. Final test не используется для выбора модели, подбора threshold, score bands story или segment narrative.

Теперь удалите `score_band` из `derived_dimensions`. Analyzer должен заблокировать contract: score-band comparison - обязательная часть урока, потому что одна и та же строка может сменить band между моделями.

Измените `budget_count` с `2` на `1`. Это уже другой decision rule. Отчет должен пересчитываться только после явного изменения policy и тестов, иначе deltas нельзя сравнивать с phase-15 handoff.

Наконец, попробуйте интерпретировать `country=RU` как стабильный production failure. Это методологическая ошибка: slice виден, но `row_count=2`, поэтому он diagnostic-only.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/07-segment-analysis/tests
```

Тесты проверяют:

- handoff от phase-15 model card, `16/03` early stopping и `16/06` SHAP;
- validation-only segment analysis без final test;
- одинаковые `snapshot_id` для baseline и CatBoost;
- changed action set: `S005` становится FP, `S006` становится FN;
- overall precision/recall/error deltas;
- 38 slice metric rows и 19 delta rows;
- 36 small-n warnings без удаления срезов;
- 13 hidden-failure slices;
- score-band shift для `S006`;
- serialized handoff для следующего урока;
- CLI и writer outputs.

Для полного курса после изменения статуса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Named artifact:

```text
phases/16-tabular-ml/07-segment-analysis/outputs/strong_model_segment_analyzer.py
```

Его можно запускать напрямую:

```bash
uv run --locked python phases/16-tabular-ml/07-segment-analysis/outputs/strong_model_segment_analyzer.py \
  --output-root phases/16-tabular-ml/07-segment-analysis/outputs
```

Handoff следующему уроку:

```text
readiness_status = ready_for_cost_sensitive_decision_lesson
```

Это не значит, что CatBoost готов к production. Это значит, что у нас есть честная сегментная evidence base для следующего вопроса: меняет ли threshold/cost policy бизнес-решение, и есть ли хоть один сценарий, где strong model полезна.

## Упражнения

1. Добавьте dimension `plan_id:platform` в копии policy и посчитайте, какие slices станут hidden failures.
2. Измените score bands на `low/medium/high/very_high` и объясните, какие rows сменили diagnostic group.
3. Поставьте `budget_count=1` в копии policy и сравните, меняется ли направление overall delta.
4. Добавьте в delta policy отдельный reason для `action_count_delta != 0` и проверьте, помогает ли он объяснить score-band slices.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Strong-model segment analysis | Достаточно сравнить средний score CatBoost и baseline | Нужно сравнить action outcome по тем же rows, budget и slice policy |
| Baseline delta | Метрики моделей можно читать отдельно | Главное число - разница CatBoost минус baseline на том же slice |
| Hidden-failure slice | Срез обязательно скрыт overall metric | В этом уроке это любой predeclared slice, где candidate хуже baseline и это нельзя замолчать |
| Small-n warning | Малый срез надо удалить | Малый срез остается в evidence table, но получает diagnostic-only статус |
| Score-band shift | `high` score band одинаков для всех моделей | Score band считается по score конкретной модели, поэтому membership может измениться |
| No-promotion warning | Модель нельзя больше исследовать | Модель нельзя продвигать как улучшение; ее можно анализировать в threshold/cost lesson |

## Дополнительное чтение

- [CatBoost: `CatBoostClassifier.fit`](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_fit) - параметры `eval_set`, `use_best_model` и связь training control с downstream comparison.
- [CatBoost: `predict_proba`](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_predict_proba) - почему score table должен сохранять feature order и probability output contract.
- [scikit-learn: metrics and scoring](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) - classification metrics, которые мы переносим из aggregate report в slice-level ledger.
- [scikit-learn: `precision_recall_fscore_support`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_fscore_support.html) - полезный API reference для проверки ручных precision/recall формул.
- [Fairlearn: Fairness in Machine Learning](https://fairlearn.org/main/user_guide/fairness_in_machine_learning.html) - чем diagnostic segment analysis отличается от полноценного fairness assessment.
